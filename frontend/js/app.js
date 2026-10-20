/* app.js —— 界面逻辑。所有后端调用都走 Api(见 api.js)。 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var state = { task: null, result: null, options: null, busy: false };

  /* ---------- 工具 ---------- */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  // 先转义,再把后端标记转成高亮
  function mark(s) {
    return esc(s)
      .replace(/\[\[待确认:([\s\S]*?)\]\]/g, '<span class="todo" title="待确认">待确认:$1</span>')
      .replace(/\[\[拦截:([\s\S]*?)\]\]/g, '<span class="blocked" title="已拦截">$1</span>');
  }
  function plain(s) {
    return String(s || '').replace(/\[\[待确认:([\s\S]*?)\]\]/g, '(待确认:$1)').replace(/\[\[拦截:[\s\S]*?\]\]/g, '');
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : ''; }
  function link(url, text) {
    var u = safeUrl(url);
    return u ? '<a class="src" href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + esc(text || u) + '</a>' : esc(text || '—');
  }
  function pill(st) {
    return st === 'ok' ? '<span class="pill">已核验</span>' : st === 'no' ? '<span class="pill no">不一致</span>' : '<span class="pill q">待确认</span>';
  }

  /* ---------- 初始化 ---------- */
  function fillSelect(sel, items, placeholder) {
    sel.innerHTML = '<option value="">' + placeholder + '</option>' + items.map(function (it) {
      var v = typeof it === 'string' ? it : it.id, n = typeof it === 'string' ? it : it.name;
      return '<option value="' + esc(v) + '">' + esc(n) + '</option>';
    }).join('');
  }

  function initStatus() {
    Api.status().then(function (s) {
      var box = $('conn');
      box.classList.toggle('ok', !!s.connected);
      box.classList.toggle('bad', !s.connected);
      $('connText').textContent = s.connected
        ? '已连接:' + s.kb_name + (s.key_masked ? '(Key ' + s.key_masked + ')' : '')
        : (s.message || s.kb_name || '未连接知识库');
      $('modeNote').textContent = Api.isMock() ? '当前为演示数据:参数与图片均为占位,不代表真实产品信息。' : '';
    }).catch(function (e) {
      $('conn').classList.add('bad');
      $('connText').textContent = '连接失败:' + e.message;
    });
  }

  function initOptions() {
    return Api.options().then(function (o) {
      state.options = o;
      fillSelect($('model'), o.models, '请选择型号');
      fillSelect($('audience'), o.audiences, '请选择人群');
      $('sceneList').innerHTML = o.scenes.map(function (s) { return '<option value="' + esc(s) + '">'; }).join('');
      $('platform').innerHTML = o.platforms.map(function (p, i) {
        return '<label><input type="radio" name="plat" value="' + esc(p.id) + '"' + (i === 0 ? ' checked' : '') + '><span>' + esc(p.name) + '</span></label>';
      }).join('');
      updateHints();
    });
  }

  function updateHints() {
    if (!state.options) return;
    var m = state.options.models.filter(function (x) { return x.id === $('model').value; })[0];
    $('modelHint').textContent = m ? (m.system || '') + (m.hint ? ' · ' + m.hint : '') : '';
    var pid = (document.querySelector('input[name=plat]:checked') || {}).value;
    var p = state.options.platforms.filter(function (x) { return x.id === pid; })[0];
    $('platHint').textContent = p ? p.hint : '';
  }

  /* ---------- 表单 ---------- */
  function readTask() {
    var p = document.querySelector('input[name=plat]:checked');
    return {
      model: $('model').value, audience: $('audience').value, scene: $('scene').value.trim(),
      platform: p ? p.value : '', extra: $('extra').value.trim()
    };
  }
  function writeTask(t) {
    if (!t) return;
    $('model').value = t.model; $('audience').value = t.audience; $('scene').value = t.scene; $('extra').value = t.extra || '';
    var r = document.querySelector('input[name=plat][value="' + t.platform + '"]');
    if (r) r.checked = true;
    updateHints();
  }
  function markInvalid(questions) {
    var t = readTask();
    ['model', 'audience', 'scene'].forEach(function (k) {
      $(k).closest('.field').classList.toggle('invalid', !t[k]);
    });
    var box = $('ask');
    box.hidden = !questions.length;
    $('askList').innerHTML = questions.map(function (q) { return '<li>' + esc(q) + '</li>'; }).join('');
    if (questions.length) box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  /* ---------- 加载进度 ---------- */
  var STEPS = ['确认任务信息', '检索知识库(产品事实 / 卖点 / 图片索引)', '按人群与平台生成软文', '事实核验与合规检查'];
  var stepTimer = null;
  function showLoading() {
    $('empty').hidden = true; $('error').hidden = true; $('result').hidden = true; $('loading').hidden = false;
    var i = 0;
    function draw() {
      $('steps').innerHTML = STEPS.map(function (s, k) {
        return '<div class="step ' + (k < i ? 'done' : k === i ? 'run' : '') + '">' + esc(s) + '</div>';
      }).join('');
    }
    draw();
    clearInterval(stepTimer);
    stepTimer = setInterval(function () { if (i < STEPS.length - 1) { i++; draw(); } }, 1200);
  }
  function stopLoading() { clearInterval(stepTimer); $('loading').hidden = true; }
  function setBusy(b) {
    state.busy = b;
    $('go').disabled = b; $('reviseGo').disabled = b;
    $('go').textContent = b ? '正在生成…' : (state.result ? '重新生成' : '生成软文');
  }
  function showError(msg) {
    stopLoading(); $('result').hidden = !state.result; $('error').hidden = false; $('error').textContent = msg;
    $('empty').hidden = !!state.result;
  }

  /* ---------- 渲染结果 ---------- */
  function renderScene(s) {
    $('sec-scene').innerHTML =
      '<dl class="kv"><dt>目标人群</dt><dd>' + esc(s.audience) + '</dd>' +
      '<dt>使用场景</dt><dd>' + esc(s.scene) + '</dd>' +
      '<dt>用户问题</dt><dd>' + esc(s.problem) + '</dd>' +
      '<dt>内容目标</dt><dd>' + esc(s.goal) + '</dd>' +
      '<dt>发布平台</dt><dd>' + esc(s.platform) + '</dd></dl>' +
      '<div class="reason"><b>为什么这样写:</b>' + esc(s.reason) + '</div>';
  }

  function renderEvidence(e) {
    var rows = (e.facts || []).map(function (f) {
      return '<tr><td>' + esc(f.point) + '</td><td>' + link(f.url, f.title) + '</td><td><code>' + esc(f.media_id || '—') + '</code></td></tr>';
    }).join('') || '<tr><td colspan="3">未检索到可引用的资料</td></tr>';
    $('sec-evidence').innerHTML =
      '<p class="h4">产品型号</p><p style="margin:0">' + esc(e.model) + '</p>' +
      '<p class="h4">事实点与资料</p><div class="table-wrap"><table><thead><tr><th>事实点</th><th>资料标题 / 原文</th><th>media_id</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      ((e.rejected || []).length ? '<p class="h4">已排除的相近型号 / 提示</p><ul class="check">' + e.rejected.map(function (r) { return '<li class="q">' + esc(r) + '</li>'; }).join('') + '</ul>' : '');
  }

  function renderArticle(a) {
    var imgs = a.images || [];
    function figs(after) {
      return imgs.filter(function (im) { return (im.after || 0) === after; }).map(function (im) {
        var u = safeUrl(im.url);
        return '<figure class="fig"><div class="ph">' + (u ? '<img src="' + esc(Api.imageUrl(u)) + '" alt="' + esc(im.caption || im.name) + '" loading="lazy" referrerpolicy="no-referrer">' : '图片占位') + '</div>' +
          '<figcaption><b>' + esc(im.name) + '</b> · 来源:' + link(im.url, im.source) + ' · 位置:' + esc(im.position) + '<br>' + esc(im.caption) + '</figcaption></figure>';
      }).join('');
    }
    var html = '<div class="article"><h4>' + mark(a.title) + '</h4><p class="lede">' + mark(a.lead) + '</p>' + figs(0);
    (a.body || []).forEach(function (p, i) { html += '<p>' + mark(p) + '</p>' + figs(i + 1); });
    html += '<p class="cta">' + mark(a.cta) + '</p><p class="tags">' + (a.tags || []).map(esc).join(' ') + '</p></div>';
    $('sec-article').innerHTML = html;
  }

  function renderVerify(v) {
    var factRows = (v.facts || []).map(function (f) {
      return '<tr><td>' + mark(f.claim) + '</td><td>' + esc(f.evidence) + '</td><td>' + pill(f.status) + '</td></tr>';
    }).join('');
    var imgRows = (v.images || []).map(function (f) {
      return '<tr><td>' + esc(f.name) + '</td><td>' + esc(f.note) + '</td><td>' + pill(f.status) + '</td></tr>';
    }).join('');
    var comp = (v.compliance || []).map(function (c) { return '<li class="' + (c.status === 'ok' ? '' : 'x') + '">' + esc(c.text) + '</li>'; }).join('');
    var pend = (v.pending || []).map(function (c) { return '<li class="q">' + esc(c) + '</li>'; }).join('');
    $('sec-verify').innerHTML =
      '<p class="h4">产品事实</p><div class="table-wrap"><table><thead><tr><th>文中表述</th><th>知识库对照</th><th>结果</th></tr></thead><tbody>' + (factRows || '<tr><td colspan="3">正文未出现具体参数</td></tr>') + '</tbody></table></div>' +
      '<p class="h4">图片与型号</p><div class="table-wrap"><table><thead><tr><th>图片</th><th>说明</th><th>结果</th></tr></thead><tbody>' + (imgRows || '<tr><td colspan="3">未使用图片</td></tr>') + '</tbody></table></div>' +
      '<p class="h4">合规检查</p><ul class="check">' + comp + '</ul>' +
      (pend ? '<p class="h4">待确认信息</p><ul class="check">' + pend + '</ul>' : '');

    var bad = 0, todo = 0;
    (v.facts || []).concat(v.images || []).forEach(function (x) { if (x.status === 'no') bad++; else if (x.status === 'todo') todo++; });
    (v.compliance || []).forEach(function (x) { if (x.status !== 'ok') bad++; });
    var b = $('verifyBadge');
    b.className = 'badge' + (bad ? ' bad' : todo || (v.pending || []).length ? ' warn' : '');
    b.textContent = bad ? '拦截/不一致 ' + bad + ' 项' : todo || (v.pending || []).length ? '待确认 ' + (todo + (v.pending || []).length) + ' 项' : '全部通过';
  }

  function render(r) {
    state.result = r;
    stopLoading(); $('error').hidden = true; $('empty').hidden = true;
    renderScene(r.scene); renderEvidence(r.evidence); renderArticle(r.article); renderVerify(r.verify);
    var box = $('result'); box.hidden = false;
    box.classList.remove('fresh'); void box.offsetWidth; box.classList.add('fresh');
    renderChips();
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderChips() {
    var ps = (state.options && state.options.platforms) || [];
    var list = ['删掉第二段', '把卖点换成续航'].concat(ps.filter(function (p) { return p.id !== state.task.platform; }).map(function (p) { return '换成' + p.name; }));
    $('chips').innerHTML = list.map(function (t) { return '<button type="button" class="chip">' + esc(t) + '</button>'; }).join('');
  }

  /* ---------- 动作 ---------- */
  function articleText() {
    var a = state.result.article, out = [a.title, '', a.lead, ''];
    a.body.forEach(function (p) { out.push(plain(p), ''); });
    out.push(plain(a.cta), '', (a.tags || []).join(' '));
    return out.join('\n');
  }

  function markdown() {
    var r = state.result, s = r.scene, e = r.evidence, a = r.article, v = r.verify, L = [];
    L.push('# 一、场景判断', '- 目标人群:' + s.audience, '- 使用场景:' + s.scene, '- 用户问题:' + s.problem, '- 内容目标:' + s.goal, '- 平台:' + s.platform, '- 判断依据:' + s.reason, '');
    L.push('# 二、知识库依据', '- 产品型号:' + e.model);
    (e.facts || []).forEach(function (f) { L.push('- ' + f.point + ' ← 《' + f.title + '》(media_id: ' + (f.media_id || '—') + (f.url ? ',' + f.url : '') + ')'); });
    L.push('', '# 三、图文软文', '## ' + a.title, '', a.lead, '');
    function figs(n) {
      (a.images || []).filter(function (im) { return (im.after || 0) === n; }).forEach(function (im) {
        L.push('> 图片:' + im.name + ' | 来源:' + (im.url || im.source) + ' | 位置:' + im.position + ' | 说明:' + im.caption, '');
      });
    }
    figs(0);
    a.body.forEach(function (p, i) { L.push(plain(p), ''); figs(i + 1); });
    L.push(plain(a.cta), '', (a.tags || []).join(' '), '');
    L.push('# 四、核验结果', '## 产品事实');
    (v.facts || []).forEach(function (f) { L.push('- [' + f.status + '] ' + plain(f.claim) + ' — ' + f.evidence); });
    L.push('## 图片型号');
    (v.images || []).forEach(function (f) { L.push('- [' + f.status + '] ' + f.name + ' — ' + f.note); });
    L.push('## 合规');
    (v.compliance || []).forEach(function (c) { L.push('- [' + c.status + '] ' + c.text); });
    if ((v.pending || []).length) { L.push('## 待确认信息'); v.pending.forEach(function (p) { L.push('- ' + p); }); }
    return L.join('\n');
  }

  function flash(btn, text) {
    var old = btn.dataset.t || btn.textContent; btn.dataset.t = old; btn.textContent = text;
    setTimeout(function () { btn.textContent = old; }, 1600);
  }

  function run(promiseFactory) {
    if (state.busy) return;
    setBusy(true); showLoading();
    promiseFactory().then(function (r) {
      if (r && r._task) { state.task = r._task; writeTask(r._task); }
      setBusy(false); render(r);
    }).catch(function (e) {
      setBusy(false);
      showError(e.name === 'AbortError' ? '请求超时,请稍后重试。' : '生成失败:' + (e.message || '未知错误'));
    });
  }

  function onSubmit(ev) {
    ev.preventDefault();
    if (state.busy) return;
    var t = readTask();
    Api.check(t).then(function (c) {
      markInvalid(c.ok ? [] : c.questions);
      if (!c.ok) return;
      state.task = t;
      run(function () { return Api.generate(t); });
    }).catch(function (e) { showError('检查失败:' + e.message); });
  }

  function revise(text) {
    text = (text || '').trim();
    if (!text || !state.result) return;
    run(function () { return Api.revise(state.task, text, state.result); });
    $('reviseText').value = '';
  }

  function bind() {
    $('form').addEventListener('submit', onSubmit);
    $('form').addEventListener('change', function () { updateHints(); });
    $('form').addEventListener('input', function (e) {
      var f = e.target.closest('.field'); if (f) f.classList.remove('invalid');
    });
    $('reviseGo').addEventListener('click', function () { revise($('reviseText').value); });
    $('reviseText').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); revise(this.value); } });
    $('chips').addEventListener('click', function (e) { var c = e.target.closest('.chip'); if (c) revise(c.textContent); });
    $('copy').addEventListener('click', function () {
      var b = this, t = articleText();
      (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(function () { flash(b, '已复制'); }, function () { flash(b, '请手动选中复制'); });
    });
    $('export').addEventListener('click', function () {
      var blob = new Blob(['﻿' + markdown()], { type: 'text/markdown;charset=utf-8' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = '软文_' + new Date().toISOString().slice(0, 10) + '.md';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    });
  }

  initOptions().then(function () { return initStatus(); }).then(bind).catch(function (e) {
    $('conn').classList.add('bad'); $('connText').textContent = '初始化失败:' + e.message; bind();
  });
})();
