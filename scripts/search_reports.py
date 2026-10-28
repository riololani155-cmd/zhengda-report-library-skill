#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""正大杯国奖报告库检索工具

用法:
  python search_reports.py 关键词 [-y 年份] [-a 国一|国二|国三]
  python search_reports.py -f 关键词        # 仅按文件名检索（快）
  python search_reports.py --stats          # 库统计
  python search_reports.py --rebuild        # 强制重建全文索引

报告库路径解析优先级：
  1. 命令行 -l / --lib 参数
  2. 环境变量 ZHENGDA_LIB
  3. 脚本内 DEFAULT_LIB 常量

首次全文检索会自动建立 SQLite 索引（约 1-2 分钟），之后每次检索秒回。
依赖：Python 3.8+，pypdf（pip install pypdf）。
"""
import argparse
import os
import re
import sqlite3
import sys

DEFAULT_LIB = os.environ.get(
    'ZHENGDA_LIB',
    r'C:\Users\24738\Desktop\正大杯\国奖报告库_2020-2025',  # 改为你的报告库路径
)
SNIPPET = 90


def out(s=''):
    sys.stdout.buffer.write((str(s) + '\n').encode('utf-8', errors='replace'))


def iter_pdfs(lib):
    for root, _dirs, files in os.walk(lib):
        for f in sorted(files):
            if f.lower().endswith('.pdf'):
                yield os.path.join(root, f)


def meta_of(fname):
    """从文件名解析年份与奖项: 【20国一】/【2023国一（...）】/【23国三】"""
    year = award = None
    m = re.search(r'【[^】]*?(\d{2,4})[^】]*?国([一二三])', fname)
    if m:
        y = m.group(1)
        year = int(y) if len(y) == 4 else 2000 + int(y)
        award = '国' + m.group(2)
    else:
        m2 = re.search(r'(20\d{2})', fname)
        if m2:
            year = int(m2.group(1))
    return year, award


def init_db(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS files(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE, name TEXT, year INTEGER, award TEXT,
            mtime REAL, size INTEGER);
        CREATE TABLE IF NOT EXISTS pages(
            file_id INTEGER, page INTEGER, text TEXT);
        CREATE INDEX IF NOT EXISTS idx_pages_file ON pages(file_id);
    ''')


def build_index(conn, lib, only=None):
    from pypdf import PdfReader
    cur = conn.cursor()
    if only is None:
        cur.execute('DELETE FROM pages')
        cur.execute('DELETE FROM files')
    n = 0
    total = len(list(iter_pdfs(lib)))
    for path in iter_pdfs(lib):
        name = os.path.basename(path)
        if only is not None and name not in only:
            continue
        year, award = meta_of(name)
        try:
            st = os.stat(path)
            reader = PdfReader(path)
            cur.execute('DELETE FROM pages WHERE file_id IN (SELECT id FROM files WHERE name=?)', (name,))
            cur.execute('DELETE FROM files WHERE name=?', (name,))
            cur.execute('INSERT INTO files(path,name,year,award,mtime,size) VALUES(?,?,?,?,?,?)',
                        (path, name, year, award, st.st_mtime, st.st_size))
            fid = cur.lastrowid
            for i, page in enumerate(reader.pages, 1):
                text = (page.extract_text() or '').replace('\x00', ' ')
                cur.execute('INSERT INTO pages VALUES(?,?,?)', (fid, i, text))
            n += 1
            out('[index] %d/%d %s' % (n, total if only is None else len(only), name))
        except Exception as e:
            out('[warn] 索引失败: %s (%s)' % (name, e))
    conn.commit()


def ensure_index(conn, lib):
    """检查是否有新增/变更的 PDF，必要时增量重建；完全没有索引则全量重建。"""
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM files')
    if cur.fetchone()[0] == 0:
        out('[index] 首次运行，正在建立全文索引（约 1-2 分钟）...')
        build_index(conn, lib)
        return
    stale = set()
    on_disk = {os.path.basename(p): p for p in iter_pdfs(lib)}
    cur.execute('SELECT name, mtime, size FROM files')
    for name, mtime, size in cur.fetchall():
        p = on_disk.pop(name, None)
        if p is None:
            stale.add(name)  # 已删除
        else:
            st = os.stat(p)
            if st.st_mtime != mtime or st.st_size != size:
                stale.add(name)  # 已变更
    for name in on_disk:
        stale.add(name)  # 新增
    if stale:
        out('[index] 检测到 %d 个文件变化，正在增量更新索引...' % len(stale))
        cur.execute('DELETE FROM pages WHERE file_id IN (SELECT id FROM files WHERE name IN (%s))'
                    % ','.join('?' * len(stale)), tuple(stale))
        cur.execute('DELETE FROM files WHERE name IN (%s)' % ','.join('?' * len(stale)), tuple(stale))
        conn.commit()
        build_index(conn, lib, only=stale)


def filter_clause(args):
    cond, params = [], []
    if args.year:
        cond.append('year = ?')
        params.append(args.year)
    if args.award:
        cond.append('award = ?')
        params.append(args.award)
    return (' WHERE ' + ' AND '.join(cond)) if cond else '', params


def search_filename(conn, kw, args):
    sql, params = filter_clause(args)
    cur = conn.cursor()
    like = '%' + kw + '%'
    cur.execute('SELECT path, name, year, award FROM files' + sql +
                (' AND ' if sql else ' WHERE ') + 'name LIKE ?', params + [like])
    return cur.fetchall()


def search_fulltext(conn, kw, args, limit_pages=8):
    """返回 {path: (matched_pages, [snippets])}"""
    cur = conn.cursor()
    sql, params = filter_clause(args)
    cur.execute('SELECT id, path FROM files' + sql, params)
    files = cur.fetchall()
    result = {}
    kw_l = kw.lower()
    for fid, path in files:
        cur.execute('SELECT page, text FROM pages WHERE file_id=?', (fid,))
        pages = 0
        snippets = []
        for page, text in cur.fetchall():
            low = text.lower()
            idx = low.find(kw_l)
            if idx >= 0:
                pages += 1
                if len(snippets) < 3:
                    s = max(0, idx - SNIPPET // 2)
                    snip = text[s:idx + SNIPPET].replace('\r', ' ').replace('\n', ' ')
                    snippets.append('P%d: …%s…' % (page, snip))
            if pages >= limit_pages and len(snippets) >= 3:
                break
        if pages:
            result[path] = (pages, snippets)
    return result


def cmd_stats(conn):
    cur = conn.cursor()
    cur.execute('SELECT year, award, COUNT(*) FROM files GROUP BY year, award ORDER BY year, award')
    for y, a, c in cur.fetchall():
        out('%s %s: %d 篇' % (y or '?', a or '?', c))
    cur.execute('SELECT COUNT(*) FROM files')
    out('总计: %d 篇' % cur.fetchone()[0])


def main():
    ap = argparse.ArgumentParser(description='正大杯国奖报告库检索')
    ap.add_argument('keyword', nargs='?', help='检索关键词（可省略搭配 --stats/--rebuild）')
    ap.add_argument('-l', '--lib', help='报告库根目录（默认取环境变量 ZHENGDA_LIB 或脚本内 DEFAULT_LIB）')
    ap.add_argument('-f', '--file-only', action='store_true', help='仅按文件名检索')
    ap.add_argument('-y', '--year', type=int, help='按年份筛选，如 2023')
    ap.add_argument('-a', '--award', choices=['国一', '国二', '国三'], help='按奖项级别筛选')
    ap.add_argument('--stats', action='store_true', help='库统计')
    ap.add_argument('--rebuild', action='store_true', help='强制重建全文索引')
    args = ap.parse_args()

    lib = args.lib or DEFAULT_LIB
    db = os.path.join(lib, '.report_index.db')

    if not os.path.isdir(lib):
        out('错误: 报告库不存在: %s' % lib)
        out('请用 -l 参数或环境变量 ZHENGDA_LIB 指定报告库目录。')
        sys.exit(2)

    if args.stats:
        conn = sqlite3.connect(db)
        init_db(conn)
        ensure_index(conn, lib)
        cmd_stats(conn)
        conn.close()
        return

    if not args.keyword:
        out('请提供关键词，或用 --stats 查看统计')
        sys.exit(2)

    conn = sqlite3.connect(db)
    init_db(conn)
    ensure_index(conn, lib)

    if args.rebuild:
        out('[index] 强制重建全文索引...')
        build_index(conn, lib)

    if args.file_only:
        rows = search_filename(conn, args.keyword, args)
        out('=== 文件名匹配 %d 篇 ===' % len(rows))
        for path, name, y, a in rows:
            out('[%s %s] %s' % (y or '?', a or '?', name))
    else:
        rows = search_filename(conn, args.keyword, args)
        out('=== 文件名匹配 %d 篇 ===' % len(rows))
        for path, name, y, a in rows[:20]:
            out('[%s %s] %s' % (y or '?', a or '?', name))
        hits = search_fulltext(conn, args.keyword, args)
        out('')
        out('=== 全文匹配 %d 篇（含页码与片段）===' % len(hits))
        for path, (pages, snippets) in sorted(hits.items(), key=lambda x: -x[1][0]):
            name = os.path.basename(path)
            y, a = meta_of(name)
            out('[%s %s] %s —— 命中 %d 页' % (y or '?', a or '?', name, pages))
            for sn in snippets:
                out('    %s' % sn)
            out('')
    conn.close()


if __name__ == '__main__':
    main()
