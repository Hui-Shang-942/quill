/*
 * api.js —— 前端与后端的唯一接口层
 *
 * 后端同学只需要实现下面 5 个 HTTP 接口(JSON),前端不用再改。
 * 密钥(ima / 大模型)只放后端环境变量,前端拿不到。
 *
 * GET  /api/status    -> { connected:bool, kb_name:str, key_masked:"ab12****", message?:str }
 * GET  /api/options   -> { models:[{id,name,system,hint}], audiences:[str], scenes:[str],
 *                          platforms:[{id,name,hint}] }
 * POST /api/check     body: Task          -> { ok:bool, questions:[str] }
 * POST /api/generate  body: Task          -> Result   (出错: HTTP 4xx/5xx + {error:str})
 * POST /api/revise    body: { task:Task, instruction:str, previous:Result } -> Result
 * GET  /api/image?url=<ima图片原始URL>  -> 图片二进制(后端带鉴权拉取并转发,前端 <img> 直接引用)
 *
 * Task   = { model, audience, scene, platform, extra }
 * Result = {
 *   scene:   { audience, scene, problem, goal, platform, reason },
 *   evidence:{ model, facts:[{ point, title, media_id, url }], rejected:[str] },
 *   article: { title, lead, body:[str], cta, tags:[str],
 *              images:[{ name, source, url, position, caption, after }] },   // after = 插在第几段之后(0=导语后)
 *   verify:  { facts:[{ claim, status:"ok"|"no"|"todo", evidence }],
 *              images:[{ name, status:"ok"|"no", note }],
 *              compliance:[{ status:"ok"|"no", text }],
 *              pending:[str] }
 * }
 * 正文中无法确认的片段用 [[待确认:xxx]] 标记,被拦截的片段用 [[拦截:xxx]] 标记,前端会高亮。
 */
(function (global) {
  'use strict';

  var CONFIG = {
    baseUrl: '',          // 同域部署留空;分开部署如 'http://127.0.0.1:8000'
    useMock: 'auto',      // 'auto' 后端不通自动用演示数据;true 强制演示;false 强制真实后端
    proxyImages: true,    // 图片经后端 /api/image 代理(ima 图片可能需要鉴权);设为 false 则直连原始 URL
    timeoutMs: 120000
  };

  function http(method, path, body) {
    var ctrl = new AbortController();
    var t = setTimeout(function () { ctrl.abort(); }, CONFIG.timeoutMs);
    return fetch(CONFIG.baseUrl + path, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal
    }).then(function (r) {
      clearTimeout(t);
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.error || ('请求失败(' + r.status + ')')); e.http = true; throw e; }
        return j;
      });
    }, function (err) { clearTimeout(t); err.network = true; throw err; });
  }

  /* ---------------- 演示数据(后端未就绪时使用,内容均为占位,不是真实参数) ---------------- */
  var MOCK_OPTIONS = {
    models: [
      { id: 'd16', name: 'MateBook D 16', system: 'Windows', hint: '与 D 16 SE 版不是同一型号' },
      { id: 'd16se', name: 'MateBook D 16 SE 版', system: 'Windows', hint: '规格低于 D 16,勿套用 i9 / 70Wh' },
      { id: 'pro', name: 'MateBook Pro', system: 'HarmonyOS', hint: '与 Pro S 参数不同' },
      { id: 'pros', name: 'MateBook Pro S', system: 'HarmonyOS', hint: '更轻,电池容量与 Pro 不同' },
      { id: 'm14', name: 'MateBook 14(鸿蒙)', system: 'HarmonyOS', hint: '与 14 酷睿 Ultra 不是同一型号' },
      { id: 'm14u', name: 'MateBook 14 酷睿 Ultra', system: 'Windows', hint: 'Windows 版与 Linux 版配置有差异' }
    ],
    audiences: ['大学新生', '商务差旅', '内容创作者', '家庭换新', '企业采购'],
    scenes: ['开学季', '职场办公', '出差途中', '剪辑与设计', '全家共用', '批量部署'],
    platforms: [
      { id: 'wechat', name: '公众号', hint: '标题、导语、分段正文、结尾引导。配图 2–4 张。' },
      { id: 'xhs', name: '小红书', hint: '口语化标题、短段落、话题标签。配图 3–6 张。不得伪造个人体验。' },
      { id: 'moments', name: '门店朋友圈', hint: '短文案,只讲 1 个核心卖点,引导咨询或到店。配图 1–3 张。' },
      { id: 'poster', name: '门店海报', hint: '主标题、副标题、不超过 3 个卖点。1 张主视觉。' }
    ]
  };

  function modelOf(task) {
    return MOCK_OPTIONS.models.filter(function (m) { return m.id === task.model; })[0] || MOCK_OPTIONS.models[0];
  }
  function platOf(task) {
    return MOCK_OPTIONS.platforms.filter(function (p) { return p.id === task.platform; })[0] || MOCK_OPTIONS.platforms[0];
  }

  var BANNED = ['终身免费', '全部覆盖', '无条件退换', '绝对兼容', '唯一', '第一', '全面领先', '零风险', '绝对安全', '最强', '碾压'];

  function mockCheck(task) {
    var q = [];
    if (!task.model) q.push('请选择产品型号。');
    if (!task.audience) q.push('目标人群是谁?例如大学新生、商务差旅。');
    if (!task.scene || !task.scene.trim()) q.push('主要使用场景是什么?例如开学季、出差。');
    if (!task.platform) q.push('要发布到哪个平台?');
    return { ok: q.length === 0, questions: q };
  }

  function mockGenerate(task) {
    var m = modelOf(task), p = platOf(task);
    var extra = task.extra || '';
    var wantPrice = /价格|补贴|优惠|折|元|券|¥/.test(extra);
    var hit = BANNED.filter(function (w) { return extra.indexOf(w) >= 0; });
    var body = [
      task.audience + '在「' + task.scene + '」里最常遇到的问题,是设备要兼顾便携、续航与日常效率。',
      m.name + ' 的具体参数,这里以知识库条目为准:[[待确认:演示数据未连接真实知识库]]。',
      '想了解当前配置与活动,请前往华为官方渠道查看。'
    ];
    if (wantPrice) body.push('[[拦截:用户要求写入价格/补贴,知识库无对应官方快照]]');
    var compliance = [
      { status: 'ok', text: '未使用绝对化用语' },
      { status: 'ok', text: '未与其他品牌作贬低性对比' },
      { status: wantPrice ? 'no' : 'ok', text: wantPrice ? '已拒绝:补充要求中的价格/补贴在知识库中无依据,未写入正文' : '未出现价格、补贴、库存、销量等承诺' }
    ];
    if (hit.length) compliance.push({ status: 'no', text: '补充要求含禁用词:' + hit.join('、') + ',已忽略' });
    var imgCount = { wechat: 2, xhs: 3, moments: 1, poster: 1 }[p.id] || 1;
    var images = [];
    for (var i = 0; i < imgCount; i++) {
      images.push({
        name: m.name.replace(/\s/g, '') + '_' + (i + 1) + '.jpg',
        source: 'ima 图片索引(演示占位)', url: '', after: i,
        position: i === 0 ? '导语之后' : '第 ' + i + ' 段之后',
        caption: '官网图片说明(演示占位)'
      });
    }
    return {
      scene: {
        audience: task.audience, scene: task.scene, platform: p.name,
        problem: '在「' + task.scene + '」中选到合适又不踩坑的电脑',
        goal: '让读者了解 ' + m.name + ' 与自己场景的匹配点,并去官方渠道确认细节',
        reason: '因为人群是「' + task.audience + '」、场景是「' + task.scene + '」,所以优先讲与该场景直接相关的卖点,并按「' + p.name + '」的结构与语气组织。'
      },
      evidence: {
        model: m.name + '(' + m.system + ')',
        facts: [{ point: '产品定位(演示)', title: m.name + ' 产品事实', media_id: 'demo-media-id', url: '' }],
        rejected: m.hint ? ['易混淆提示:' + m.hint] : []
      },
      article: {
        title: p.name + '|' + task.scene + '选 ' + m.name + ',我看重这三点',
        lead: '先说结论:' + task.audience + '选电脑,先看场景,再看参数。',
        body: body, cta: '想看详细参数,可到华为官方渠道或附近门店了解。',
        tags: ['#华为PC', '#' + m.name.replace(/[\s()()]/g, ''), '#' + task.scene], images: images
      },
      verify: {
        facts: [
          { claim: '型号:' + m.name, status: 'ok', evidence: '与所选型号一致' },
          { claim: '具体参数', status: 'todo', evidence: '演示模式未接入知识库' }
        ],
        images: images.map(function (im) { return { name: im.name, status: 'ok', note: '演示占位,真实环境将校验型号字段' }; }),
        compliance: compliance,
        pending: ['演示模式:参数与图片均为占位,请连接后端后重新生成']
      }
    };
  }

  function mockRevise(task, instruction, prev) {
    var t = JSON.parse(JSON.stringify(task));
    var map = { '朋友圈': 'moments', '公众号': 'wechat', '小红书': 'xhs', '海报': 'poster' };
    Object.keys(map).forEach(function (k) { if (instruction.indexOf(k) >= 0) t.platform = map[k]; });
    var r = mockGenerate(t);
    var m = instruction.match(/删掉第(\d+)段/);
    if (m) r.article.body.splice(+m[1] - 1, 1);
    r._task = t;
    return r;
  }

  function delay(v, ms) { return new Promise(function (res) { setTimeout(function () { res(v); }, ms); }); }

  /* ---------------- 对外 API ---------------- */
  var mockMode = false;
  function call(real, mock) {
    if (CONFIG.useMock === true) { mockMode = true; return mock(); }
    return real().catch(function (e) {
      if (CONFIG.useMock === 'auto' && e.network) { mockMode = true; return mock(); }
      throw e;
    });
  }

  global.Api = {
    config: CONFIG,
    isMock: function () { return mockMode; },
    imageUrl: function (url) {
      if (!url) return '';
      if (!CONFIG.proxyImages || mockMode) return url;
      return CONFIG.baseUrl + '/api/image?url=' + encodeURIComponent(url);
    },
    status: function () {
      return call(function () { return http('GET', '/api/status'); },
        function () { return delay({ connected: false, kb_name: '演示模式(未连接后端)', key_masked: '', message: '后端未启动,当前为演示数据' }, 300); });
    },
    options: function () {
      return call(function () { return http('GET', '/api/options'); }, function () { return delay(MOCK_OPTIONS, 100); });
    },
    check: function (task) {
      return call(function () { return http('POST', '/api/check', task); }, function () { return delay(mockCheck(task), 80); });
    },
    generate: function (task) {
      return call(function () { return http('POST', '/api/generate', task); }, function () { return delay(mockGenerate(task), 1800); });
    },
    revise: function (task, instruction, previous) {
      return call(function () { return http('POST', '/api/revise', { task: task, instruction: instruction, previous: previous }); },
        function () { return delay(mockRevise(task, instruction, previous), 1500); });
    }
  };
})(window);
