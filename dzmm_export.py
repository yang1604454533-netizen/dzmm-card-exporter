#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
dzmm_export.py  ——  把 dzmm.ai 的角色导出成 SillyTavern(酒馆) 能直接导入的 v2 角色卡 PNG

为什么需要它:
    dzmm 网页上的卡图是 CDN 转出来的 WebP，而且原始 PNG 里也没有 chara 数据块，
    所以右键另存 -> 拖进酒馆 = 必然失败。
    本脚本直接从站点接口取「角色名 / 角色介绍 / 标签 / 作者 / 封面原图」，
    按 chara_card_v2 规范组装 JSON，base64 后写进 PNG 的 tEXt "chara" 数据块。

用法:
    # 单张 / 多张（URL 或纯数字 id 都行）
    python dzmm_export.py 3674281 https://www.dzmm.ai/character/3689641 --out D:\cards

    # 整个榜单（newest / games / highest_rated_1d / _7d / _30d / _all / competition ...）
    python dzmm_export.py --tab highest_rated_7d --out D:\cards

    # 某个作者的全部卡（作者主页 URL 或 userId）
    python dzmm_export.py --creator <作者主页URL或userId> --out D:\cards

    # id 列表文件（每行一个 id 或 URL）
    python dzmm_export.py --list ids.txt --out D:\cards

    # 顺手把开场白写进去（站点不提供 firstMes，见下方说明）
    python dzmm_export.py --tab newest --first-mes-file opener.txt --out D:\cards

    # 只导出卡信息为 json，不下载图
    python dzmm_export.py 3674281 --json-only

⚠️ 站点 firstMes 字段全站为空字符串，所以开场白导不出来。用 --first-mes / --first-mes-file
   可以给这一批卡统一塞一段开场白；不塞的话，角色设定是完整的，开场白留空。
"""
import argparse, base64, io, json, os, re, struct, sys, time, urllib.error, urllib.parse, urllib.request, zlib

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
SITE = "https://www.dzmm.ai"
RENDER = "/storage/v1/render/image/public/"
OBJECT = "/storage/v1/object/public/"
JS_STR = r'"(?:[^"\\]|\\.)*"'
TABS = ["green_featured", "newest", "following", "for_you", "games", "newbie_recommendation",
        "highest_rated_1d", "highest_rated_7d", "highest_rated_30d", "highest_rated_all",
        "categories", "draw", "competition"]


# ---------------------------------------------------------------- HTTP
def http_get(url, referer=SITE + "/", timeout=60, retries=4):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "*/*", "Referer": referer,
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def trpc(proc, payload):
    body = {"json": payload, "meta": {"values": {"categoryName": ["undefined"]}, "v": 1}}
    url = "%s/api/trpc/%s?input=%s" % (SITE, proc, urllib.parse.quote(json.dumps(body, ensure_ascii=False)))
    return json.loads(http_get(url).decode("utf-8"))


# ---------------------------------------------------------------- RSC 解析
def js_unescape(lit):
    s, out, i = lit[1:-1], [], 0
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.append(c); i += 1; continue
        n = s[i + 1]; i += 2
        if n == "n": out.append("\n")
        elif n == "r": out.append("\r")
        elif n == "t": out.append("\t")
        elif n == "b": out.append("\b")
        elif n == "f": out.append("\f")
        elif n == "u": out.append(chr(int(s[i:i + 4], 16))); i += 4
        else: out.append(n)
    return "".join(out)


def brace_slice(text, start):
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n:
                if text[i] == "\\": i += 2; continue
                if text[i] == '"': break
                i += 1
        elif c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0: return text[start:i + 1]
        i += 1
    return ""


def field(block, key):
    m = re.search(r"[,{]" + re.escape(key) + r":(" + JS_STR + r")", block)
    return js_unescape(m.group(1)) if m else None


def tags_of(block):
    m = re.search(r"[,{]tags:\$R\[\d+\]=\[((?:" + JS_STR + r")(?:,(?:" + JS_STR + r"))*)\]", block)
    return [js_unescape(x) for x in re.findall(JS_STR, m.group(1))] if m else []


def fetch_card(card_id):
    page = "%s/character/%d" % (SITE, card_id)
    html = http_get(page).decode("utf-8", "replace")
    i = html.find("characterData:")
    if i < 0:
        raise RuntimeError("页面里没有 characterData（卡片可能已删除/需要登录）")
    block = brace_slice(html, html.index("{", i))

    name = desc = og = None
    mi = html.rfind("meta:$R[", 0, i)
    if mi >= 0:
        mb = brace_slice(html, html.index("{", mi))
        name, desc, og = field(mb, "name"), field(mb, "description"), field(mb, "ogImage")

    notes = field(block, "creatorNotes")
    return {
        "id": card_id,
        "name": name or field(block, "name") or ("dzmm-%d" % card_id),
        "description": desc or notes or "",
        "creator_notes": notes or desc or "",
        "first_mes": field(block, "firstMes") or "",
        "creator": field(block, "creatorFullName") or "",
        "tags": tags_of(block),
        "creator_id": field(block, "userId"),
        "cover_render": og,
        "page": page,
    }


def cover_url(render_url):
    return render_url.split("?")[0].replace(RENDER, OBJECT) if render_url else None


# ---------------------------------------------------------------- PNG
def to_png(raw):
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw                      # 站点封面直链本来就是 PNG，正常走这条
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("封面不是 PNG，需要 Pillow 转格式。请执行: python -m pip install Pillow")
    im = Image.open(io.BytesIO(raw))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    buf = io.BytesIO(); im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def add_text_chunk(png, keyword, text):
    ln = struct.unpack(">I", png[8:12])[0]
    pos = 8 + 12 + ln                                    # 紧跟 IHDR
    payload = keyword.encode("latin-1") + b"\x00" + text.encode("latin-1")
    chunk = struct.pack(">I", len(payload)) + b"tEXt" + payload
    chunk += struct.pack(">I", zlib.crc32(b"tEXt" + payload) & 0xFFFFFFFF)
    return png[:pos] + chunk + png[pos:]


def build_v2(d):
    data = {
        "name": d["name"], "description": d["description"], "personality": "",
        "scenario": "", "first_mes": d["first_mes"], "mes_example": "",
        "creator_notes": d["creator_notes"], "system_prompt": "",
        "post_history_instructions": d.get("post_history") or "",
        "alternate_greetings": [],
        "character_book": None, "tags": d["tags"], "creator": d["creator"],
        "character_version": "1.0",
        "extensions": {"dzmm": {"id": d["id"], "url": d["page"]}},
    }
    card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": data}
    for k in ("name", "description", "personality", "scenario", "first_mes", "mes_example"):
        card[k] = data[k]                               # v1 兼容
    return card


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", s).strip(" .")
    return (s[:80] or "card")


# 长回复要求：站点那边的长回复来自它的「预设」（规则 / 文风 / 记忆增强 等），
# 卡片本身不带。这里把它写进卡的 post_history_instructions，导进酒馆就自带。
LONG_REPLY_PHI = """[输出要求 · 必须遵守]
1. 篇幅：每次回复不少于 800 字，宁长勿短。禁止用一两句话概括整段剧情。
2. 结构：用多个自然段展开，每段 3~5 句。依次覆盖——环境与氛围、{{char}} 的动作过程、神态与表情、身体细节与反应、内心活动、对话内容。
3. 对白：要有语气、停顿、口癖和情绪起伏，写完整的句子，不要只丢结论式的短句。
4. 动作：写出过程与因果，不要跳过中间步骤，不要用"然后……"一笔带过。
5. 感官：调动视觉、听觉、触觉、嗅觉、温度与体感，让场景可被感知。
6. 禁止：不要替 {{user}} 说话、行动或做决定；不要总结已发生的剧情；不要跳时间；不要用"你想怎么做？"之类的方式收尾。
7. 结尾：留一个自然、可供 {{user}} 接话的钩子（一个动作、一句话或一个悬念），不要收束。
"""


# ================================================================ 开场白抓取
# 站点公开接口的 firstMes 是空的，但每张卡其实有一个**固定**的开场白 ——
# 它只在「对话分享(checkpoint)」里露出来：一段分享对话的第 1 条角色消息就是它。
# 已验证：同一张卡的不同分享，第 1 条角色消息完全一致。

def get_checkpoints(card_id, creator_id=None):
    """取一张卡的对话分享列表。creatorId 是必填参数，不传就先抓一次卡片拿 userId。"""
    if creator_id is None:
        creator_id = fetch_card(card_id).get("creator_id")
    body = {"json": {"cardId": int(card_id), "creatorId": creator_id}}
    url = "%s/api/trpc/card.getPageSections?input=%s" % (
        SITE, urllib.parse.quote(json.dumps(body, ensure_ascii=False)))
    j = json.loads(http_get(url, referer="%s/character/%s" % (SITE, card_id)).decode("utf-8"))
    return (j.get("result", {}).get("data", {}).get("json", {}) or {}).get("checkpoints") or []


def _html_to_text(inner):
    inner = re.sub(r"</p>\s*<p[^>]*>", "\n", inner)
    inner = re.sub(r"<br\s*/?>", "\n", inner)
    inner = re.sub(r"<[^>]+>", "", inner)
    import html as _h
    return _h.unescape(inner).strip()


def first_character_message(html):
    """从分享页 HTML 里取第一条「角色」消息（用户消息带 flex-row-reverse）。"""
    parts = re.split(r'(?=<div class="flex items-start gap-2 sm:gap-2\.5)', html)
    for p in parts:
        if "rounded-2xl" not in p:
            continue
        m = re.match(r'<div class="flex items-start gap-2 sm:gap-2\.5([^"]*)"', p)
        if m and "flex-row-reverse" in m.group(1):
            continue                      # 这是用户发的
        b = re.search(r'<div class="rounded-2xl[^"]*">(.*?)</div></div></div>', p, re.S)
        txt = _html_to_text(b.group(1) if b else p)
        if txt:
            return txt
    return None


def has_earlier_marker(html):
    return bool(re.search(r"还有\s*\d+\s*条更早的消息", html))


def opening_probe(card_id, max_checks=10):
    """一次搞定：返回 (抓到的开场白或 None, [必须登录才能展开的 shareCode...])
    免登录的短分享在 Python 侧直接解析掉；剩下的交给前端 iframe + 登录态去展开。
    """
    d = fetch_card(card_id)
    need = []
    try:
        cps = get_checkpoints(card_id, d.get("creator_id"))
    except Exception:
        return None, need
    for c in cps[:max_checks]:
        code = c.get("shareCode")
        if not code:
            continue
        try:
            h = http_get("%s/share/%s" % (SITE, code), referer=d["page"]).decode("utf-8", "replace")
        except Exception:
            continue
        if has_earlier_marker(h):
            need.append(code)             # 只渲染了最后几条，得登录展开
            continue
        txt = first_character_message(h)
        if txt and len(txt) > 40:
            return txt, need
    return None, need


def opening_from_card(d, max_checks=8, verbose=False):
    """不用登录的最好-effort 抓法：找一个「本来就没有更早消息」的分享，
    这种分享页会把整段对话都渲染出来，第 1 条角色消息就是开场白。
    需要展开（>5 条消息）的分享必须登录，这里跳过。
    """
    try:
        cps = get_checkpoints(d["id"], d.get("creator_id"))
    except Exception as e:
        if verbose:
            print("     取对话分享失败: %s" % e)
        return None, None
    for c in cps[:max_checks]:
        code = c.get("shareCode")
        if not code:
            continue
        try:
            h = http_get("%s/share/%s" % (SITE, code), referer=d["page"]).decode("utf-8", "replace")
        except Exception:
            continue
        if has_earlier_marker(h):
            continue                      # 只渲染了最后几条，第 1 条不是开场白
        txt = first_character_message(h)
        if txt and len(txt) > 40:
            return txt, c
    return None, None


# ---------------------------------------------------------------- 批量取 id
def ids_from_tab(tab):
    cs = trpc("home.getCards", {"type": tab, "categoryName": None, "direction": "forward"})
    return [c["id"] for c in cs["result"]["data"]["json"]]


def ids_from_creator(who):
    url = who if who.startswith("http") else "%s/user/%s" % (SITE, who)
    html = http_get(url).decode("utf-8", "replace")
    ids, seen = [], set()
    for m in re.findall(r"/character/(\d{3,})", html):
        if m not in seen:
            seen.add(m); ids.append(int(m))
    return ids


# ---------------------------------------------------------------- 主流程
def export_one(cid, outdir, opener, write_json, skip_existing=True, json_only=False,
               auto_opening=False, long_reply=False):
    d = fetch_card(cid)
    if long_reply:
        d["post_history"] = LONG_REPLY_PHI
    if opener:
        d["first_mes"] = opener
    elif auto_opening:
        grabbed, cp = opening_from_card(d)
        if grabbed:
            d["first_mes"] = grabbed
            d["_opening_source"] = (cp or {}).get("shareCode")
            d["_opening_grabbed"] = True
    path = os.path.join(outdir, safe_name(d["name"]) + ".png")
    if skip_existing and os.path.exists(path):
        return path, d, "skip"
    if json_only:
        path = os.path.join(outdir, safe_name(d["name"]) + ".json")
        json.dump(build_v2(d), open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return path, d, "json"
    cu = cover_url(d["cover_render"])
    if not cu:
        raise RuntimeError("拿不到封面地址")
    png = add_text_chunk(to_png(http_get(cu, referer=d["page"])), "chara",
                         base64.b64encode(json.dumps(build_v2(d), ensure_ascii=False).encode("utf-8")).decode("ascii"))
    open(path, "wb").write(png)
    if write_json:
        json.dump(build_v2(d), open(path[:-4] + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return path, d, "ok"


def main():
    ap = argparse.ArgumentParser(description="dzmm.ai -> SillyTavern v2 角色卡导出")
    ap.add_argument("cards", nargs="*", help="角色页 URL 或纯数字 id")
    ap.add_argument("--tab", choices=TABS, help="整榜导出")
    ap.add_argument("--creator", help="作者主页 URL 或 userId")
    ap.add_argument("--list", dest="listfile", help="id/URL 列表文件，每行一个")
    ap.add_argument("--top", type=int, default=0, help="只导出前 N 张")
    ap.add_argument("--out", default=".", help="输出目录")
    ap.add_argument("--first-mes", default=None, help="统一写入的开场白")
    ap.add_argument("--first-mes-file", default=None, help="从文件读取开场白")
    ap.add_argument("--delay", type=float, default=1.2, help="每次请求间隔秒数（站点有 429 限流）")
    ap.add_argument("--json", action="store_true", help="同时输出 .json")
    ap.add_argument("--json-only", action="store_true", help="只输出 .json，不下图")
    ap.add_argument("--long-reply", action="store_true",
                    help="把「长回复要求」写进卡的后历史指令(Post-History Instructions)，导入酒馆后回复会变长")
    ap.add_argument("--auto-opening", action="store_true",
                    help="自动从该卡的对话分享里抓开场白（不用登录，但只对短分享有效）")
    ap.add_argument("--no-skip", action="store_true", help="覆盖已存在的文件")
    a = ap.parse_args()

    opener = a.first_mes
    if a.first_mes_file:
        opener = open(a.first_mes_file, encoding="utf-8").read()
    if opener is not None:
        opener = opener.replace("\r\n", "\n")

    ids, seen = [], set()

    def push(x):
        if x not in seen:
            seen.add(x); ids.append(x)

    for raw in a.cards:
        m = re.search(r"(\d{4,})", raw)
        if m: push(int(m.group(1)))
        else: print("跳过（无法解析）:", raw)
    if a.listfile:
        for line in open(a.listfile, encoding="utf-8"):
            m = re.search(r"(\d{4,})", line)
            if m: push(int(m.group(1)))
    if a.creator:
        for i in ids_from_creator(a.creator): push(i)
    if a.tab:
        for i in ids_from_tab(a.tab): push(i)
    if a.top:
        ids = ids[:a.top]
    if not ids:
        ap.print_help(); return

    os.makedirs(a.out, exist_ok=True)
    print("共 %d 张，输出到 %s\n" % (len(ids), os.path.abspath(a.out)))
    ok = fail = skip = 0
    for n, cid in enumerate(ids, 1):
        try:
            path, d, st = export_one(cid, a.out, opener, a.json, not a.no_skip, a.json_only,
                                     auto_opening=a.auto_opening, long_reply=a.long_reply)
            if st == "skip": skip += 1; flag = "SKIP"
            else: ok += 1; flag = "OK  "
            print("[%s] %3d/%d  %-38s -> %s" % (flag, n, len(ids), d["name"][:38], os.path.basename(path)))
            src = "手动" if opener else ("自动抓到" if d.get("_opening_grabbed") else "")
            print("          标签: %s | 作者: %s | 开场白: %s" % (
                ",".join(d["tags"]) or "无", d["creator"] or "无",
                ("已写入(%s, %d字)" % (src, len(d["first_mes"]))) if d["first_mes"]
                else "空(需自行补写)"))
        except Exception as e:
            fail += 1
            print("[FAIL] %3d/%d  %s : %s" % (n, len(ids), cid, e))
        time.sleep(a.delay)
    print("\n完成: 成功 %d / 跳过 %d / 失败 %d" % (ok, skip, fail))


if __name__ == "__main__":
    # 输出被重定向到文件/管道时，用 UTF-8 写，避免中文变乱码；真实控制台保持默认。
    for _s in (sys.stdout, sys.stderr):
        try:
            if not _s.isatty():
                _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
