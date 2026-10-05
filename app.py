# -*- coding: utf-8 -*-
r"""
DZMM 角色卡导出器 —— 图形界面版

    python app.py

做三件事:
    1. 内嵌 dzmm.ai（真实 WebView2 内核，搜索/切页签/翻页/登录 都照常可用）
    2. 鼠标悬停任意角色图 -> 出现「导出角色卡」按钮；点它就生成酒馆 v2 卡 PNG 存到本地
       Alt/⌘+点击图片 也直接导出；面板里还能开「直接点图片即导出」
    3. 右下角悬浮面板：改保存目录、写开场白、覆盖开关、导出当前页角色、查看日志

本文件依赖同目录的 dzmm_export.py（取数 / 组装 chara_card_v2 / 写 PNG）。
"""
import json
import os
import re
import subprocess
import sys
import threading
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

try:
    import webview
except ImportError:
    print("缺少 pywebview，请先执行:  python -m pip install pywebview")
    raise

import dzmm_export as core   # noqa: E402

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
INJECT_PATH = os.path.join(APP_DIR, "inject.js")
WEBVIEW_DATA = os.path.join(APP_DIR, "webview_data")
HOME_URL = "https://www.dzmm.ai/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0")

# Windows 用 WebView2(Edge)；macOS 用系统 WebKit；Linux 交给 pywebview 自己挑 gtk/qt
GUI_BY_PLATFORM = {"win32": "edgechromium", "darwin": "cocoa"}

DEFAULT_OUT = os.path.join(os.path.expanduser("~"), "Downloads", "DZMM角色卡")


def load_config():
    cfg = {"outdir": DEFAULT_OUT, "click_mode": True, "overwrite": False, "opener": "",
           "write_json": False, "long_reply": True}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def pick_window_size():
    """给一个肯定落在屏幕可视区里的 窗口尺寸 + 位置（pywebview 自己的居中在 200% 缩放下会跑到屏幕外）。"""
    sw, sh = 1440, 900
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        r.destroy()
    except Exception:
        pass
    w = max(980, min(1500, sw - 100))
    h = max(660, min(940, sh - 160))     # 留出任务栏 + 标题栏
    return w, h, 24, 24


class Api:
    def __init__(self):
        self.cfg = load_config()
        self._window = None      # 名字必须以下划线开头：pywebview 会反射 js_api，碰到 Window 对象会无限递归
        self.lock = threading.Lock()
        self.busy = set()
        os.makedirs(self.cfg["outdir"], exist_ok=True)

    # ---------------- 状态 ----------------
    def get_state(self):
        return {
            "outdir": self.cfg["outdir"],
            "click_mode": bool(self.cfg["click_mode"]),
            "overwrite": bool(self.cfg["overwrite"]),
            "opener": self.cfg.get("opener", ""),
            "long_reply": bool(self.cfg.get("long_reply", True)),
        }

    def set_click_mode(self, on):
        self.cfg["click_mode"] = bool(on)
        save_config(self.cfg)
        return {"ok": True}

    # ---------------- 目录 ----------------
    def choose_dir(self):
        try:
            fd = getattr(webview, "FileDialog", None)
            kind = fd.FOLDER if fd else 20          # 20 == FileDialog.FOLDER
            res = self._window.create_file_dialog(kind, directory=self.cfg["outdir"])
            if not res:
                return {"ok": False}
            path = res[0] if isinstance(res, (list, tuple)) else res
            self.cfg["outdir"] = str(path)
            save_config(self.cfg)
            os.makedirs(self.cfg["outdir"], exist_ok=True)
            return {"ok": True, "outdir": self.cfg["outdir"]}
        except Exception as e:
            return {"ok": False, "error": "无法打开目录选择器：%s（可手动改 config.json 里的 outdir）" % e}

    def open_outdir(self):
        """在系统文件管理器里打开导出目录（跨平台）。"""
        try:
            os.makedirs(self.cfg["outdir"], exist_ok=True)
            p = self.cfg["outdir"]
            if sys.platform.startswith("win"):
                os.startfile(p)                       # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------- 对话分享 ----------------
    def get_checkpoints(self, card_id):
        """取这张卡的「对话分享」列表，返回 shareCode 给前端去 iframe 里挖开场白。"""
        m = re.search(r"(\d{3,})", str(card_id))
        if not m:
            return {"ok": False, "codes": [], "error": "无效的角色 id"}
        try:
            opening, need = core.opening_probe(int(m.group(1)))
            return {"ok": True, "opening": opening, "codes": need[:4]}
        except Exception as e:
            return {"ok": False, "opening": None, "codes": [], "error": "%s: %s" % (type(e).__name__, e)}

    def get_long_reply_text(self):
        """给面板上的「复制要求文本」用：可以直接粘到酒馆的全局后历史指令/预设里。"""
        return {"ok": True, "text": core.LONG_REPLY_PHI}

    # ---------------- 导出 ----------------
    def export_card(self, card_id, opener="", overwrite=False, json_only=False, long_reply=True):
        m = re.search(r"(\d{3,})", str(card_id))
        if not m:
            return {"ok": False, "error": "无效的角色 id：%s" % card_id}
        cid = int(m.group(1))

        with self.lock:
            if cid in self.busy:
                return {"ok": False, "error": "这个角色正在导出中"}
            self.busy.add(cid)
        try:
            opener = (opener or "").replace("\r\n", "\n").strip() or None
            outdir = self.cfg["outdir"]
            os.makedirs(outdir, exist_ok=True)
            path, d, st = core.export_one(
                cid, outdir, opener,
                write_json=self.cfg.get("write_json", False),
                skip_existing=not overwrite,
                json_only=bool(json_only),
                long_reply=bool(long_reply),
            )
            self.cfg["long_reply"] = bool(long_reply)
            # 记住这次用的开场白，下次打开面板还是它
            if opener:
                self.cfg["opener"] = opener
            self.cfg["overwrite"] = bool(overwrite)
            save_config(self.cfg)
            return {"ok": True, "skipped": st == "skip", "name": d["name"],
                    "file": os.path.basename(path), "path": path,
                    "tags": d["tags"], "creator": d["creator"]}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        finally:
            with self.lock:
                self.busy.discard(cid)


def inject(window):
    """页面加载完成后注入我们的脚本（SPA 路由切换不会重载页面，脚本会一直活着）。"""
    def on_loaded():
        try:
            with open(INJECT_PATH, encoding="utf-8") as f:
                code = f.read()
        except Exception as e:
            print("读不到 inject.js:", e)
            return
        for i in range(6):
            try:
                window.run_js(code)
                return
            except Exception as e:
                print("注入第 %d 次失败: %s" % (i + 1, e))
                import time
                time.sleep(0.6)

    window.events.loaded += on_loaded
    return window


def start_selftest(window, api, grab_id=None, grab_share=None):
    """--selftest：等页面起来后，自动检查注入是否成功，并真实导出第一张卡。
    --grab <id> 可以指定测哪张卡的开场白抓取。"""
    def worker():
        import time
        # 站点页面很重，onload 有时十几秒才到；先等注入脚本就位再测
        for _ in range(70):
            time.sleep(1)
            try:
                if window.evaluate_js("!!(window.__dzmmKit && window.__dzmmKit.grabOpening)"):
                    break
            except Exception:
                pass
        time.sleep(1)
        try:
            info = window.evaluate_js(
                "JSON.stringify({kit: !!window.__dzmmKit, "
                "api: !!(window.pywebview && window.pywebview.api), "
                "links: document.querySelectorAll('a[href*=\"/character/\"]').length, "
                "imgs: document.images.length})")
            print("[SELFTEST] 页面状态:", info, flush=True)

            href = window.evaluate_js(
                "var a=document.querySelector('a[href*=\"/character/\"]');"
                "a? a.getAttribute('href') : ''")
            print("[SELFTEST] 第一张卡链接:", href, flush=True)
            m = re.search(r"(\d+)", str(href or ""))
            if not m:
                print("[SELFTEST] 没找到角色链接，失败", flush=True)
            else:
                res = api.export_card(m.group(1), "", False, False)
                print("[SELFTEST] 导出结果:", json.dumps(res, ensure_ascii=False), flush=True)

            panel = window.evaluate_js("!!document.getElementById('dzmmkit-panel')")
            btn = window.evaluate_js("!!document.getElementById('dzmmkit-export')")
            print("[SELFTEST] 悬浮面板:", panel, " 导出按钮:", btn, flush=True)

            if grab_id:
                m = re.match(r"(\d+)", str(grab_id))
            if grab_share:
                started2 = window.evaluate_js(
                    "(function(){var k=window.__dzmmKit; if(!k||!k.grabFromShare) return 'no-hook';"
                    "window.__dzmmGrab2='pending';"
                    "k.grabFromShare('%s',12000).then(function(r){"
                    "window.__dzmmGrab2=JSON.stringify({ok:r.ok,reason:r.reason,len:(r.text||'').length});"
                    "}).catch(function(e){window.__dzmmGrab2='ERR '+e;});"
                    "return 'started';})()" % grab_share)
                print("[SELFTEST] iframe 单分享测试启动:", started2, flush=True)
                time.sleep(20)
                print("[SELFTEST] iframe 单分享结果:",
                      window.evaluate_js("window.__dzmmGrab2"), flush=True)
            if m:
                started = window.evaluate_js(
                    "(function(){var k=window.__dzmmKit; if(!k||!k.grabOpening) return 'no-hook';"
                    "window.__dzmmGrab='pending';"
                    "k.grabOpening('%s').then(function(r){"
                    "window.__dzmmGrab=JSON.stringify({ok:r.ok,reason:r.reason,"
                    "len:(r.text||'').length,head:(r.text||'').slice(0,50)});"
                    "}).catch(function(e){window.__dzmmGrab='ERR '+e;});"
                    "return 'started';})()" % m.group(1))
                print("[SELFTEST] 开场白抓取启动:", started, flush=True)
                time.sleep(26)
                print("[SELFTEST] 开场白抓取结果:",
                      window.evaluate_js("window.__dzmmGrab"), flush=True)

            print("[SELFTEST] DONE", flush=True)
        except Exception:
            traceback.print_exc()
        finally:
            time.sleep(2)
            try:
                window.destroy()
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()


def main():
    import logging
    for _name in ("pywebview", "webview"):
        logging.getLogger(_name).setLevel(logging.WARNING)

    os.makedirs(WEBVIEW_DATA, exist_ok=True)
    os.makedirs(DEFAULT_OUT, exist_ok=True)

    # 站点的外部跳转（Telegram 等）交给系统浏览器；放行下载；不在调试模式弹 devtools
    for _k, _v in (("ALLOW_DOWNLOADS", True),
                   ("OPEN_EXTERNAL_LINKS_IN_BROWSER", True),
                   ("OPEN_DEVTOOLS_IN_DEBUG", False)):
        try:
            webview.settings[_k] = _v
        except Exception:
            pass

    api = Api()
    w, h, wx, wy = pick_window_size()
    window = webview.create_window(
        "DZMM 角色卡导出器",
        HOME_URL,
        js_api=api,
        width=w,
        height=h,
        x=wx,
        y=wy,
        min_size=(980, 640),
        text_select=True,
        zoomable=True,
    )
    api._window = window
    inject(window)

    if "--selftest" in sys.argv:
        grab_id = None
        grab_share = None
        if "--grab" in sys.argv:
            i = sys.argv.index("--grab")
            if i + 1 < len(sys.argv):
                grab_id = sys.argv[i + 1]
        if "--grabshare" in sys.argv:
            i = sys.argv.index("--grabshare")
            if i + 1 < len(sys.argv):
                grab_share = sys.argv[i + 1]
        start_selftest(window, api, grab_id, grab_share)

    # debug=True 是为了拿到右键菜单和 F5 刷新等浏览器加速键；devtools 已在上面的设置里关掉
    try:
        webview.start(gui=GUI_BY_PLATFORM.get(sys.platform), debug=True, private_mode=False,
                      storage_path=WEBVIEW_DATA, user_agent=UA)
    except Exception as e:
        traceback.print_exc()
        print("\n窗口内核启动失败：%s" % e)
        if sys.platform.startswith("win"):
            print("请确认已安装 Microsoft Edge WebView2 Runtime 后重试。")
        elif sys.platform == "darwin":
            print("macOS 需要 pywebview 的 WebKit 后端：python -m pip install pywebview")
        else:
            print("Linux 需要 GTK 或 Qt 后端，例如：python -m pip install 'pywebview[gtk]'")
        raise


if __name__ == "__main__":
    main()
