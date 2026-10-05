/* DZMM 角色卡导出器 —— 注入到站点的脚本
 * 功能: 悬停卡图显示「导出角色卡」按钮 / Alt+点击 或 (开启开关后) 直接点击图片即导出
 * 所有取数、建卡、写盘都在 Python 侧完成，这里只负责找到角色 id 并调用 pywebview.api
 */
(function () {
  'use strict';
  var W = window;
  if (W.__dzmmKit && W.__dzmmKit.installed) { W.__dzmmKit.refresh(); return; }

  var S = {
    ready: false, outdir: '', clickMode: true, overwrite: false, autoOpening: true, longReply: true,
    opener: '', busy: 0, collapsed: false, logs: [], lastId: null
  };
  var ui = {};
  var kit = W.__dzmmKit = { installed: true, refresh: function () { try { buildUI(); } catch (e) {} } };
  // 给 app.py --selftest / --grabshare 用的钩子
  kit.grabOpening = function (id) { return grabOpening(id); };
  kit.grabFromShare = function (code, ms) { return grabFromShare(code, ms || 6500); };

  /* ---------------------------------------------------------------- 找角色 id */
  function idFromHref(h) {
    var m = String(h || '').match(/\/character\/(\d+)/);
    return m ? m[1] : null;
  }
  function findCardId(el) {
    var n = el, i, links;
    for (i = 0; i < 12 && n && n.nodeType === 1; i++, n = n.parentElement) {
      if (n.tagName === 'A') { var a = idFromHref(n.getAttribute('href')); if (a) return a; }
      if (n.getAttribute && n.getAttribute('data-card-id')) return n.getAttribute('data-card-id');
      links = n.querySelectorAll ? n.querySelectorAll('a[href*="/character/"]') : [];
      if (links.length === 1) return idFromHref(links[0].getAttribute('href'));
      if (links.length > 1) break;
    }
    var m = location.pathname.match(/\/character\/(\d+)/);
    return m ? m[1] : null;
  }
  function isCardImage(img) {
    if (!img || img.tagName !== 'IMG') return false;
    if (img.naturalWidth < 90 || img.naturalHeight < 90) return false;
    var r = img.getBoundingClientRect();
    if (r.width < 90 || r.height < 90) return false;
    var a = img.closest ? img.closest('a[href*="/user/"]') : null;
    if (a) return false;
    return true;
  }

  /* ---------------------------------------------------------------- 样式 */
  var CSS = [
    '#dzmmkit-panel{position:fixed;right:14px;bottom:14px;width:296px;z-index:2147483000;',
    'font:13px/1.5 "Microsoft YaHei",system-ui,sans-serif;color:#e8eaf0;background:rgba(24,26,34,.96);',
    'border:1px solid rgba(255,255,255,.14);border-radius:12px;box-shadow:0 10px 34px rgba(0,0,0,.5);overflow:hidden;backdrop-filter:blur(6px)}',
    '#dzmmkit-panel *{box-sizing:border-box}',
    '#dzmmkit-panel .hd{display:flex;align-items:center;gap:6px;padding:8px 10px;background:rgba(255,255,255,.07);cursor:default}',
    '#dzmmkit-panel .hd b{font-size:13px;font-weight:600;flex:1}',
    '#dzmmkit-panel .hd button{all:unset;cursor:pointer;padding:2px 7px;border-radius:6px;color:#c9cddb;font-size:12px}',
    '#dzmmkit-panel .hd button:hover{background:rgba(255,255,255,.14);color:#fff}',
    '#dzmmkit-panel .bd{padding:10px;display:block}',
    '#dzmmkit-panel.collapsed .bd{display:none}',
    '#dzmmkit-panel .row{display:flex;align-items:center;gap:6px;margin-bottom:8px}',
    '#dzmmkit-panel .lbl{color:#98a0b5;flex:0 0 auto;font-size:12px}',
    '#dzmmkit-panel .dir{flex:1;font-size:11px;color:#8ad0ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;direction:rtl;text-align:left}',
    '#dzmmkit-panel textarea{width:100%;height:52px;resize:vertical;background:#12141b;color:#e8eaf0;border:1px solid rgba(255,255,255,.16);border-radius:7px;padding:6px;font:12px/1.45 inherit}',
    '#dzmmkit-panel input[type=checkbox]{accent-color:#4f8cff;margin:0 2px 0 0}',
    '#dzmmkit-panel .chk{display:flex;align-items:center;gap:4px;color:#c9cddb;font-size:12px;cursor:pointer;user-select:none}',
    '#dzmmkit-panel .btns{display:flex;gap:6px;flex-wrap:wrap}',
    '#dzmmkit-panel .btn{all:unset;cursor:pointer;padding:5px 10px;border-radius:7px;background:rgba(255,255,255,.1);color:#e8eaf0;font-size:12px}',
    '#dzmmkit-panel .btn:hover{background:rgba(255,255,255,.2)}',
    '#dzmmkit-panel .btn.pri{background:#3b6fe0}#dzmmkit-panel .btn.pri:hover{background:#4a7ff0}',
    '#dzmmkit-log{margin-top:8px;max-height:104px;overflow:auto;font-size:11px;color:#9aa3b8;border-top:1px solid rgba(255,255,255,.1);padding-top:6px}',
    '#dzmmkit-log div{margin-bottom:2px;word-break:break-all}',
    '#dzmmkit-log .ok{color:#6ee7a8}#dzmmkit-log .err{color:#ff8f8f}',
    '#dzmmkit-export{position:fixed;z-index:2147482999;display:none;all:unset;cursor:pointer;',
    'padding:7px 12px;border-radius:9px;background:#3b6fe0;color:#fff;font:600 13px/1 "Microsoft YaHei",sans-serif;',
    'box-shadow:0 6px 20px rgba(0,0,0,.45);border:1px solid rgba(255,255,255,.25)}',
    '#dzmmkit-export:hover{background:#4a7ff0}',
    '#dzmmkit-export[data-busy="1"]{background:#7a5cf0}',
    '#dzmmkit-toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:2147483001;display:flex;flex-direction:column;gap:8px;align-items:center;pointer-events:none}',
    '#dzmmkit-toast div{background:rgba(20,22,30,.97);border:1px solid rgba(255,255,255,.18);color:#e8eaf0;padding:9px 16px;border-radius:9px;font:13px/1.4 "Microsoft YaHei",sans-serif;box-shadow:0 8px 26px rgba(0,0,0,.5);max-width:70vw}',
    '#dzmmkit-toast div.ok{border-color:#2f8f5b}#dzmmkit-toast div.err{border-color:#a33}#dzmmkit-toast div.busy{border-color:#5a5ad0}'
  ].join('');

  /* ---------------------------------------------------------------- UI */
  function buildUI() {
    if (!document.body) return;
    if (!document.getElementById('dzmmkit-style')) {
      var st = document.createElement('style');
      st.id = 'dzmmkit-style'; st.textContent = CSS;
      document.head.appendChild(st);
    }
    if (!document.getElementById('dzmmkit-toast')) {
      var t = document.createElement('div'); t.id = 'dzmmkit-toast'; document.body.appendChild(t);
    }
    if (!document.getElementById('dzmmkit-export')) {
      var eb = document.createElement('button');
      eb.id = 'dzmmkit-export'; eb.type = 'button'; eb.textContent = '导出角色卡';
      eb.addEventListener('click', function (ev) {
        ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation();
        if (eb.__id) doExport(eb.__id);
      }, true);
      eb.addEventListener('mousedown', function (ev) { ev.stopPropagation(); }, true);
      document.body.appendChild(eb); ui.exportBtn = eb;
    }
    if (document.getElementById('dzmmkit-panel')) { syncPanel(); return; }

    var p = document.createElement('div');
    p.id = 'dzmmkit-panel';
    p.innerHTML = [
      '<div class="hd"><b>DZMM 角色卡导出器</b>',
      '<button id="dzmmkit-min" title="折叠">—</button></div>',
      '<div class="bd">',
      '  <div class="row"><span class="lbl">保存到</span><span class="dir" id="dzmmkit-dir">…</span>',
      '    <button class="btn" id="dzmmkit-pick">更改</button></div>',
      '  <div class="row"><label class="chk"><input type="checkbox" id="dzmmkit-click" checked>直接点图片即导出</label>',
      '    <label class="chk"><input type="checkbox" id="dzmmkit-ow">覆盖已存在</label></div>',
      '  <div class="row"><label class="chk"><input type="checkbox" id="dzmmkit-autoop" checked>自动抓开场白</label>',
      '    <button class="btn" id="dzmmkit-grab">抓当前页开场白</button></div>',
      '  <div class="row"><label class="chk" title="写进卡的后历史指令，导入酒馆后回复会变长"><input type="checkbox" id="dzmmkit-long" checked>写长回复要求</label>',
      '    <button class="btn" id="dzmmkit-copyphi">复制要求文本</button></div>',
      '  <div style="color:#98a0b5;font-size:12px;margin-bottom:4px">开场白（可选，站点不提供）</div>',
      '  <textarea id="dzmmkit-opener" placeholder="留空则开场白为空；填了会同时套用到之后导出的卡"></textarea>',
      '  <div class="btns" style="margin-top:8px">',
      '    <button class="btn pri" id="dzmmkit-cur">导出当前页角色</button>',
      '    <button class="btn" id="dzmmkit-open">打开目录</button>',
      '    <button class="btn" id="dzmmkit-json">导出JSON</button>',
      '  </div>',
      '  <div id="dzmmkit-log"></div>',
      '</div>'
    ].join('');
    document.body.appendChild(p);
    ui.panel = p;

    document.getElementById('dzmmkit-min').addEventListener('click', function () {
      S.collapsed = !S.collapsed;
      p.classList.toggle('collapsed', S.collapsed);
      this.textContent = S.collapsed ? '+' : '—';
      try { localStorage.setItem('dzmmkit.collapsed', S.collapsed ? '1' : '0'); } catch (e) {}
    });
    document.getElementById('dzmmkit-pick').addEventListener('click', function () { pickDir(); });
    document.getElementById('dzmmkit-open').addEventListener('click', function () { api('open_outdir', []); });
    document.getElementById('dzmmkit-json').addEventListener('click', function () { jsonOnly = true; exportCurrent(); jsonOnly = false; });
    document.getElementById('dzmmkit-cur').addEventListener('click', function () { exportCurrent(); });
    document.getElementById('dzmmkit-click').addEventListener('change', function () {
      S.clickMode = this.checked; api('set_click_mode', [this.checked]);
    });
    document.getElementById('dzmmkit-ow').addEventListener('change', function () { S.overwrite = this.checked; });
    document.getElementById('dzmmkit-autoop').addEventListener('change', function () { S.autoOpening = this.checked; });
    document.getElementById('dzmmkit-grab').addEventListener('click', function () { grabCurrentOpening(); });
    document.getElementById('dzmmkit-long').addEventListener('change', function () { S.longReply = this.checked; });
    document.getElementById('dzmmkit-copyphi').addEventListener('click', function () { copyPhi(); });
    document.getElementById('dzmmkit-opener').addEventListener('change', function () { S.opener = this.value; });

    try { if (localStorage.getItem('dzmmkit.collapsed') === '1') { S.collapsed = true; p.classList.add('collapsed'); document.getElementById('dzmmkit-min').textContent = '+'; } } catch (e) {}
    syncPanel();
  }

  var jsonOnly = false;

  function syncPanel() {
    if (!ui.panel) return;
    var d = document.getElementById('dzmmkit-dir');
    if (d) { d.textContent = S.outdir || '…'; d.title = S.outdir || ''; }
    var c = document.getElementById('dzmmkit-click'); if (c) c.checked = !!S.clickMode;
    var o = document.getElementById('dzmmkit-ow'); if (o) o.checked = !!S.overwrite;
    var ao = document.getElementById('dzmmkit-autoop'); if (ao) ao.checked = !!S.autoOpening;
    var lr = document.getElementById('dzmmkit-long'); if (lr) lr.checked = !!S.longReply;
    var op = document.getElementById('dzmmkit-opener'); if (op && op.value !== S.opener) op.value = S.opener || '';
  }

  function toast(msg, kind, ms) {
    var box = document.getElementById('dzmmkit-toast');
    if (!box) return null;
    var el = document.createElement('div');
    el.className = kind || ''; el.textContent = msg;
    box.appendChild(el);
    if (!ms) ms = kind === 'busy' ? 0 : 3200;
    if (ms) setTimeout(function () { el.remove(); }, ms);
    return el;
  }
  function log(msg, kind) {
    S.logs.unshift({ m: msg, k: kind || '' });
    S.logs = S.logs.slice(0, 40);
    var box = document.getElementById('dzmmkit-log');
    if (box) {
      box.innerHTML = '';
      S.logs.slice(0, 12).forEach(function (x) {
        var d = document.createElement('div'); d.className = x.k; d.textContent = x.m; box.appendChild(d);
      });
    }
  }

  /* ---------------------------------------------------------------- 与 Python 通信 */
  function api(method, args) {
    return new Promise(function (resolve, reject) {
      if (!W.pywebview || !W.pywebview.api || !W.pywebview.api[method]) {
        reject(new Error('Python 接口未就绪')); return;
      }
      var r;
      try { r = W.pywebview.api[method].apply(W.pywebview.api, args); }
      catch (e) { reject(e); return; }
      if (r && typeof r.then === 'function') r.then(resolve, reject); else resolve(r);
    });
  }

  function pickDir() {
    api('choose_dir', []).then(function (r) {
      if (r && r.ok) { S.outdir = r.outdir; syncPanel(); toast('保存目录已改为 ' + r.outdir, 'ok'); }
      else if (r && r.error) { toast(r.error, 'err'); }
    }).catch(function (e) { toast('打开目录选择器失败: ' + e.message, 'err'); });
  }

  /* ---------------------------------------------------------------- 抓开场白
   * 站点的 firstMes 永远是空的，但每张卡其实有一个固定开场白 ——
   * 它只出现在「对话分享(/share/<code>)」里：一段分享对话的第 1 条角色消息就是它。
   * 短分享(<=5条)不用登录就能整段渲染；长分享需要登录后点「查看更早消息」展开。
   * 这里用同源 <iframe> 把分享页加载进来，直接操作它的 DOM。
   */
  var openingCache = {};

  function iframeMarker(doc) {
    var t = (doc.body && (doc.body.innerText || doc.body.textContent)) || '';
    var m = t.match(/还有\s*(\d+)\s*条更早的消息/);
    return m ? parseInt(m[1], 10) : 0;
  }

  function iframeEarlierButton(doc) {
    var bs = doc.querySelectorAll('button');
    for (var i = 0; i < bs.length; i++) {
      if ((bs[i].textContent || '').indexOf('查看更早消息') >= 0) return bs[i];
    }
    return null;
  }

  function iframeFirstMessage(doc) {
    var cont = doc.querySelector('main div.space-y-5');
    if (!cont) return null;
    var rows = cont.children;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (!row.querySelector) continue;
      var bubble = row.querySelector('div.rounded-2xl');
      if (!bubble) continue;
      if ((row.className || '').indexOf('flex-row-reverse') >= 0) continue;   // 用户消息
      var txt = (bubble.innerText || bubble.textContent || '').trim();
      if (txt) return txt;
    }
    return null;
  }

  function grabFromShare(shareCode, timeoutMs) {
    return new Promise(function (resolve) {
      var ifr = document.createElement('iframe');
      ifr.style.cssText = 'position:fixed;left:-10000px;top:0;width:1200px;height:900px;border:0;';
      var done = false, clicked = false, t0 = Date.now(), lastMarker = -1;
      function finish(v) {
        if (done) return;
        done = true;
        try { ifr.remove(); } catch (e) {}
        resolve(v);
      }
      function poll() {
        if (done) return;
        if (Date.now() - t0 > timeoutMs) {
          finish({ ok: false, reason: lastMarker > 0 ? 'need-login' : 'timeout' });
          return;
        }
        var doc = null;
        try { doc = ifr.contentDocument; } catch (e) { finish({ ok: false, reason: 'cross-origin' }); return; }
        if (!doc || !doc.body || !doc.querySelector('main div.space-y-5')) { setTimeout(poll, 300); return; }
        var marker = iframeMarker(doc);
        lastMarker = marker;
        if (marker > 0) {
          if (!clicked) {
            var b = iframeEarlierButton(doc);
            if (b) { clicked = true; try { b.click(); } catch (e) {} }
          }
          setTimeout(poll, 600);
          return;
        }
        var txt = iframeFirstMessage(doc);
        if (txt && txt.length > 20) { finish({ ok: true, text: txt }); return; }
        setTimeout(poll, 400);
      }
      ifr.onload = poll;
      ifr.src = '/share/' + shareCode;
      document.body.appendChild(ifr);
    });
  }

  function grabOpening(cardId) {
    if (openingCache[cardId]) return Promise.resolve({ ok: true, text: openingCache[cardId], cached: true });
    return api('get_checkpoints', [String(cardId)]).then(function (r) {
      if (r && r.opening) {                    // Python 侧免登录就挖到了
        openingCache[cardId] = r.opening;
        return { ok: true, text: r.opening, free: true };
      }
      var codes = (r && r.codes) || [];
      if (!codes.length) return { ok: false, reason: '这张卡没有可用的对话分享' };
      var i = 0, last = { ok: false, reason: 'timeout' };
      function next() {
        if (i >= codes.length || i >= 4) return last;
        return grabFromShare(codes[i++], 6500).then(function (res) {
          if (res.ok) { openingCache[cardId] = res.text; return res; }
          last = res;
          return next();
        });
      }
      return next();
    });
  }

  function copyPhi() {
    api('get_long_reply_text', []).then(function (r) {
      var t = (r && r.text) || '';
      if (!t) { toast('拿不到文本', 'err'); return; }
      var done = function () { toast('长回复要求已复制，可粘到酒馆的「后历史指令」或全局预设里', 'ok', 4200); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(t).then(done, function () { fallbackCopy(t, done); });
      } else fallbackCopy(t, done);
    });
  }

  function fallbackCopy(text, done) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;left:-9999px;';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
      done();
    } catch (e) { toast('复制失败：' + e.message, 'err'); }
  }

  function grabCurrentOpening() {
    var m = location.pathname.match(/\/character\/(\d+)/);
    if (!m) { toast('当前页面不是角色详情页', 'err'); return; }
    var b = toast('正在抓开场白…（可能需要几秒）', 'busy');
    grabOpening(m[1]).then(function (r) {
      if (b) b.remove();
      if (r.ok) {
        var ta = document.getElementById('dzmmkit-opener');
        if (ta) ta.value = r.text;
        S.opener = r.text;
        toast('抓到 ' + r.text.length + ' 字，已填进开场白框', 'ok');
        log('开场白已填入输入框（' + r.text.length + ' 字）', 'ok');
      } else {
        toast('没抓到：' + r.reason, 'err');
        log('抓开场白失败：' + r.reason, 'err');
      }
    });
  }

  function exportCurrent() {
    var m = location.pathname.match(/\/character\/(\d+)/);
    if (!m) { toast('当前页面不是角色详情页', 'err'); return; }
    doExport(m[1], true);
  }

  function doExport(id, isCurrent) {
    if (!id) return;
    if (S.busyIds && S.busyIds[id]) { toast('这个角色正在导出中…', 'busy'); return; }
    S.busyIds = S.busyIds || {}; S.busyIds[id] = true;
    var b = toast('正在导出角色 ' + id + ' …', 'busy');
    setExportBtnBusy(true);

    // 开场白：输入框里有就用手输的；没有且开了自动抓，就去对话分享里挖
    var openerP;
    if (S.opener) openerP = Promise.resolve(S.opener);
    else if (S.autoOpening) {
      b.textContent = '正在抓开场白…';
      openerP = grabOpening(id).then(function (g) {
        if (g.ok) { log('自动抓到开场白 ' + g.text.length + ' 字', 'ok'); return g.text; }
        log('没抓到开场白：' + g.reason, 'err');
        if (g.reason === 'need-login') toast('长对话分享需要登录后才能展开，先用空开场白导出', 'err', 4200);
        return '';
      });
    } else openerP = Promise.resolve('');

    openerP.then(function (txt) {
      b.textContent = '正在导出角色 ' + id + ' …';
      return api('export_card', [String(id), txt || '', !!S.overwrite, !!jsonOnly, !!S.longReply]);
    }).then(function (r) {
      if (r && r.ok) {
        toast((r.skipped ? '已存在，跳过：' : '已保存：') + r.name, 'ok');
        log((r.skipped ? '跳过 ' : '保存 ') + r.name + (r.file ? '  →  ' + r.file : ''), 'ok');
      } else {
        var e = (r && r.error) || '未知错误';
        toast('导出失败：' + e, 'err'); log('失败 ' + id + '：' + e, 'err');
      }
    }).catch(function (e) {
      toast('导出失败：' + (e && e.message ? e.message : e), 'err');
      log('失败 ' + id + '：' + e, 'err');
    }).then(function () {
      if (b) b.remove();
      S.busyIds[id] = false;
      setExportBtnBusy(false);
    });
  }

  function setExportBtnBusy(on) {
    if (!ui.exportBtn) return;
    ui.exportBtn.dataset.busy = on ? '1' : '0';
    ui.exportBtn.textContent = on ? '导出中…' : '导出角色卡';
  }

  /* ---------------------------------------------------------------- 悬停覆盖按钮 */
  function hideBtn() { if (ui.exportBtn) { ui.exportBtn.style.display = 'none'; ui.exportBtn.__id = null; } }
  function placeBtn(img) {
    var b = ui.exportBtn; if (!b) return;
    var r = img.getBoundingClientRect();
    b.style.display = 'block';
    var x = r.right - b.offsetWidth - 10;
    var y = r.top + 10;
    b.style.left = Math.max(6, Math.min(W.innerWidth - b.offsetWidth - 6, x)) + 'px';
    b.style.top = Math.max(6, Math.min(W.innerHeight - b.offsetHeight - 6, y)) + 'px';
  }

  document.addEventListener('mouseover', function (e) {
    var img = (e.target instanceof Element) ? e.target.closest('img') : null;
    if (!img || !isCardImage(img)) { return; }
    var id = findCardId(img);
    if (!id) { hideBtn(); return; }
    if (ui.exportBtn && ui.exportBtn.__id === id && ui.exportBtn.style.display === 'block') { placeBtn(img); return; }
    if (ui.exportBtn) { ui.exportBtn.__id = id; placeBtn(img); }
  }, true);

  document.addEventListener('mouseout', function (e) {
    var img = (e.target instanceof Element) ? e.target.closest('img') : null;
    if (!img) return;
    setTimeout(function () {
      var h = document.querySelector(':hover');
      if (!h) hideBtn();
    }, 260);
  }, true);

  W.addEventListener('scroll', hideBtn, true);
  W.addEventListener('resize', hideBtn);

  /* ---------------------------------------------------------------- 点击拦截 */
  document.addEventListener('click', function (e) {
    var el = (e.target instanceof Element) ? e.target : null;
    if (!el) return;
    if (el.closest && el.closest('#dzmmkit-panel')) return;
    if (el.id === 'dzmmkit-export') return;

    var img = el.closest('img');
    if (!img) return;
    var id = findCardId(img);
    var force = e.altKey || e.ctrlKey || e.metaKey;

    if (!id) {
      if (force) { e.preventDefault(); e.stopPropagation(); toast('这张图不对应角色卡', 'err'); }
      return;
    }
    if (force || S.clickMode) {
      e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
      hideBtn();
      doExport(id);
    }
  }, true);

  document.addEventListener('auxclick', function (e) {
    var el = (e.target instanceof Element) ? e.target : null;
    if (!el) return;
    var img = el.closest ? el.closest('img') : null;
    if (img && (e.altKey || e.ctrlKey)) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  /* ---------------------------------------------------------------- 启动 */
  function init() {
    buildUI();
    api('get_state', []).then(function (s) {
      if (!s) return;
      S.outdir = s.outdir || ''; S.clickMode = !!s.click_mode;
      S.overwrite = !!s.overwrite; S.opener = s.opener || '';
      S.longReply = s.long_reply !== false;
      S.ready = true; syncPanel();
      log('就绪。保存目录：' + S.outdir, 'ok');
      toast('导出器已就绪：鼠标悬停卡图点「导出角色卡」，或直接点图片', 'ok', 4200);
    }).catch(function () { setTimeout(init, 600); });
  }
  if (W.pywebview && W.pywebview.api) setTimeout(init, 60);
  else W.addEventListener('pywebviewready', function () { setTimeout(init, 60); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { try { buildUI(); } catch (e) {} });
  else buildUI();
})();
