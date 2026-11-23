/* DUAL // SELF — giao diện tư vấn AI. Chỉ nói chuyện với backend; không chứa khóa API. */
(function () {
  "use strict";
  var API = (window.DUAL_API_BASE || "").replace(/\/$/, "");
  var LS = "dualself.token";
  var token = localStorage.getItem(LS) || "", user = null, cfg = { moods: [], topics: [], hotlines: [] };
  var convId = null, ctx = { mood: null, topic: null }, busy = false, view = "chat", msgs = [];

  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  var tel = function (n) { return String(n).replace(/[^0-9+]/g, ""); };
  var $ = function (s, r) { return (r || document).querySelector(s); };

  /* ---------- gọi API ---------- */
  function api(path, opt, retried) {
    opt = opt || {};
    var h = { "Content-Type": "application/json" };
    if (token) h.Authorization = "Bearer " + token;
    return fetch(API + "/api" + path, { method: opt.method || "GET", headers: h, body: opt.body ? JSON.stringify(opt.body) : undefined })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (r.status === 401 && !retried && !opt.noAuth) {
            return guestLogin().then(function () { return api(path, opt, true); });
          }
          if (!r.ok) { var e = new Error(j.message || "Có lỗi xảy ra"); e.status = r.status; throw e; }
          return j;
        });
      });
  }
  function guestLogin() {
    return api("/auth/guest", { method: "POST", noAuth: true }).then(function (j) { setSession(j); });
  }
  function setSession(j) { token = j.token; user = j.user; localStorage.setItem(LS, token); }
  function ensureAuth() {
    if (user) return Promise.resolve();
    if (!token) return guestLogin();
    return api("/auth/me").then(function (j) { user = j.user; }).catch(function () { return guestLogin(); });
  }

  /* ---------- khung giao diện ---------- */
  var root = document.createElement("div");
  root.innerHTML =
    '<div class="scrim" id="aiScrim"></div>' +
    '<aside class="drawer" id="aiDrawer" role="dialog" aria-modal="true" aria-labelledby="aiTitle" aria-hidden="true">' +
    '<div class="d-head"><button class="back" id="aiBack" hidden aria-label="Quay lại">‹</button>' +
    '<h2 id="aiTitle">Bạn đồng hành AI<small>AI lắng nghe, không thay thế chuyên gia</small></h2>' +
    '<div class="d-actions"><button id="aiNew" aria-label="Cuộc trò chuyện mới" title="Mới">＋</button>' +
    '<button id="aiHist" aria-label="Lịch sử" title="Lịch sử">☰</button>' +
    '<button id="aiAcct" aria-label="Tài khoản" title="Tài khoản">☺</button>' +
    '<button id="aiClose" aria-label="Đóng">✕</button></div></div>' +
    '<div class="d-body" id="aiBody" aria-live="polite"></div>' +
    '<form class="ai-foot" id="aiFoot"><div class="quick" id="aiMoods" role="group" aria-label="Tâm trạng"></div>' +
    '<div class="ai-row"><label class="sr-only" for="aiInput">Nhập tin nhắn</label>' +
    '<textarea id="aiInput" rows="1" maxlength="1500" placeholder="Bạn muốn tâm sự điều gì?"></textarea>' +
    '<button class="icon-btn" id="aiSend" type="submit" aria-label="Gửi" disabled>➤</button></div></form></aside>';
  document.body.appendChild(root);
  var drawer = $("#aiDrawer"), scrim = $("#aiScrim"), body = $("#aiBody"), foot = $("#aiFoot"), input = $("#aiInput"), sendBtn = $("#aiSend");

  function open() { drawer.classList.add("open"); scrim.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); ensureAuth().then(loadCfg).then(function () { if (view === "chat") renderChat(); else render(); input.focus(); }).catch(showErr); }
  function close() { drawer.classList.remove("open"); scrim.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); var b = $("#openAI"); if (b) b.focus(); }
  function loadCfg() { return cfg.moods.length ? Promise.resolve() : api("/config", { noAuth: true }).then(function (j) { cfg = j; drawMoods(); }); }
  function showErr(e) { body.innerHTML = '<p class="empty">Không kết nối được máy chủ AI. ' + esc(e.message || "") + "</p>"; }

  function drawMoods() {
    $("#aiMoods").innerHTML = cfg.moods.map(function (m) { return '<button type="button" aria-pressed="' + (ctx.mood === m) + '" data-m="' + esc(m) + '">' + esc(m) + "</button>"; }).join("");
  }
  $("#aiMoods").addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (!b) return;
    ctx.mood = ctx.mood === b.dataset.m ? null : b.dataset.m; drawMoods();
  });

  /* ---------- hiển thị ---------- */
  function careCard(level, resources, withAI) {
    if (!resources || !resources.length) return "";
    var title = level >= 3 ? "Hãy liên hệ người thật ngay bây giờ" : "Bạn không phải một mình";
    return '<div class="care ' + (level >= 3 ? "crisis" : "") + '"><b>' + title + "</b>" +
      "<ul>" + resources.map(function (r) {
        return "<li><span>" + esc(r.name) + "<small>" + esc(r.hours) + "</small></span><a class=\"call\" href=\"tel:" + tel(r.number) + "\">" + esc(r.number) + "</a></li>";
      }).join("") + "</ul>" +
      (withAI ? '<div class="row2"><button type="button" data-act="ai">Nói chuyện với AI</button><button type="button" data-act="dismiss">Đóng</button></div>' : "") + "</div>";
  }
  function bubble(m) {
    var cls = m.role === "user" ? "me" : "ai-them";
    var h = '<div class="msg ' + cls + '">' + esc(m.content) + "</div>";
    if (m.sources && m.sources.length) h += '<div class="srcs" title="Nguồn kiến thức tham khảo">' + m.sources.map(function (s) { return "<span>📖 " + esc(s.title) + "</span>"; }).join("") + "</div>";
    if (m.care) h += careCard(m.care.level, m.care.resources, false);
    return h;
  }
  function renderChat() {
    view = "chat"; $("#aiBack").hidden = true; foot.hidden = false;
    var intro = '<div class="ctx">Mình là <b>AI</b>, không phải chuyên gia tâm lý và không chẩn đoán bệnh. Nếu bạn cần người thật: <b>111</b> (bảo vệ trẻ em, 24/7) · <b>115</b> (cấp cứu).</div>';
    if (!msgs.length) intro += '<p class="empty">Bạn đang nghĩ gì vậy? Mình ở đây để nghe nè.</p>';
    body.innerHTML = intro + msgs.map(bubble).join("") + (busy ? '<div class="msg ai-them"><div class="typing" aria-label="AI đang trả lời"><i></i><i></i><i></i></div></div>' : "");
    body.scrollTop = body.scrollHeight;
  }
  function renderHistory() {
    view = "history"; $("#aiBack").hidden = false; foot.hidden = true;
    api("/conversations").then(function (j) {
      body.innerHTML = j.conversations.length ? j.conversations.map(function (c) {
        return '<div class="conv-item"><button class="convo" data-id="' + c.id + '"><div class="meta"><b>' + esc(c.title) + "</b><span>" + esc(c.last) + '</span></div></button><button class="del" data-del="' + c.id + '" aria-label="Xoá">🗑</button></div>';
      }).join("") : '<p class="empty">Chưa có cuộc trò chuyện nào.</p>';
    }).catch(showErr);
  }
  function renderAccount(err) {
    view = "account"; $("#aiBack").hidden = false; foot.hidden = true;
    if (user && !user.is_guest) {
      body.innerHTML = '<div class="acct"><div class="ctx">Đang đăng nhập: <b>' + esc(user.username || user.alias) + "</b> · vai trò <b>" + esc(user.role) + "</b></div>" +
        (user.role === "admin" || user.role === "teacher" ? '<a class="primary" style="text-align:center;text-decoration:none;color:inherit" href="' + API + '/admin">Mở bảng quản trị</a>' : "") +
        '<button class="primary" id="aiLogout" type="button">Đăng xuất</button></div>';
      return;
    }
    body.innerHTML = '<div class="acct"><div class="ctx">Bạn đang dùng <b>' + esc(user ? user.alias : "") + "</b> (ẩn danh). Phụ huynh và giáo viên đăng nhập để dùng đúng vai trò.</div>" +
      '<form id="aiLogin" class="acct"><label>Tên đăng nhập<input name="username" autocomplete="username" required></label>' +
      '<label>Mật khẩu<input name="password" type="password" autocomplete="current-password" required></label>' +
      '<label id="aiRoleWrap" hidden>Vai trò<select name="role"><option value="parent">Phụ huynh</option><option value="teacher">Giáo viên</option><option value="student">Học sinh</option></select></label>' +
      '<label id="aiInvWrap" hidden>Mã mời của nhà trường (giáo viên)<input name="invite_code"></label>' +
      '<p class="err" id="aiErr">' + esc(err || "") + '</p><button class="primary" type="submit" id="aiAuthBtn">Đăng nhập</button>' +
      '<button class="link" type="button" id="aiToggle">Chưa có tài khoản? Đăng ký</button></form></div>';
  }
  function render() { ({ chat: renderChat, history: renderHistory, account: renderAccount })[view](); }

  /* ---------- sự kiện ---------- */
  var composing = function (e) { return e.isComposing || e.keyCode === 229; };
  input.addEventListener("input", function () { sendBtn.disabled = !input.value.trim() || busy; input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 120) + "px"; });
  input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey && !composing(e)) { e.preventDefault(); foot.requestSubmit(); } });
  foot.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim(); if (!text || busy) return;
    msgs.push({ role: "user", content: text }); input.value = ""; input.style.height = "auto"; sendBtn.disabled = true; busy = true; renderChat();
    api("/chat", { method: "POST", body: { message: text, conversation_id: convId, context: ctx } }).then(function (j) {
      convId = j.conversation_id;
      var m = j.message; m.care = j.risk.level >= 2 ? { level: j.risk.level, resources: j.resources } : null;
      msgs.push(m);
    }).catch(function (err) {
      msgs.push({ role: "assistant", content: err.status === 429 ? "Bạn nhắn hơi nhanh, đợi mình một chút nhé." : "Mình chưa kết nối được lúc này. Nếu bạn đang cần giúp ngay, hãy gọi 111 hoặc 115." });
    }).then(function () { busy = false; renderChat(); sendBtn.disabled = !input.value.trim(); });
  });
  function newChat() { convId = null; msgs = []; view = "chat"; renderChat(); input.focus(); }
  $("#aiNew").addEventListener("click", newChat);
  $("#aiHist").addEventListener("click", function () { renderHistory(); });
  $("#aiAcct").addEventListener("click", function () { renderAccount(); });
  $("#aiBack").addEventListener("click", function () { renderChat(); });
  $("#aiClose").addEventListener("click", close);
  scrim.addEventListener("click", close);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && drawer.classList.contains("open")) close(); });

  body.addEventListener("click", function (e) {
    var c = e.target.closest(".convo"), d = e.target.closest("[data-del]");
    if (c) {
      api("/conversations/" + c.dataset.id).then(function (j) {
        convId = j.conversation.id;
        msgs = j.messages.map(function (m) { return { role: m.role, content: m.content, sources: m.sources, care: null }; });
        renderChat();
      }).catch(showErr);
    } else if (d && confirm("Xoá cuộc trò chuyện này?")) {
      api("/conversations/" + d.dataset.del, { method: "DELETE" }).then(function () { if (convId == d.dataset.del) { convId = null; msgs = []; } renderHistory(); });
    } else if (e.target.id === "aiLogout") {
      api("/auth/logout", { method: "POST" }).catch(function () {}).then(function () { localStorage.removeItem(LS); token = ""; user = null; convId = null; msgs = []; return ensureAuth(); }).then(function () { renderAccount(); });
    } else if (e.target.id === "aiToggle") {
      var reg = $("#aiAuthBtn").textContent === "Đăng nhập";
      $("#aiAuthBtn").textContent = reg ? "Đăng ký" : "Đăng nhập";
      e.target.textContent = reg ? "Đã có tài khoản? Đăng nhập" : "Chưa có tài khoản? Đăng ký";
      $("#aiRoleWrap").hidden = !reg; $("#aiInvWrap").hidden = !reg || $("[name=role]", body).value !== "teacher";
    }
  });
  body.addEventListener("change", function (e) { if (e.target.name === "role") $("#aiInvWrap").hidden = e.target.value !== "teacher"; });
  body.addEventListener("submit", function (e) {
    if (e.target.id !== "aiLogin") return; e.preventDefault();
    var f = e.target, reg = $("#aiAuthBtn").textContent === "Đăng ký";
    var payload = { username: f.username.value.trim(), password: f.password.value };
    if (reg) { payload.role = f.role.value; payload.invite_code = f.invite_code.value; }
    api(reg ? "/auth/register" : "/auth/login", { method: "POST", body: payload, noAuth: true })
      .then(function (j) { setSession(j); convId = null; msgs = []; renderAccount(); })
      .catch(function (err) { renderAccount(err.message); });
  });

  /* ---------- Safety cho bài đăng / bình luận / tin nhắn riêng ở giao diện cũ ---------- */
  var care = document.createElement("div"); care.id = "aiCare";
  var composer = $(".composer"); if (composer) composer.insertAdjacentElement("afterend", care);
  function onPost(text, source) {
    if (!text || text.trim().length < 3) return;
    fetch(API + "/api/safety/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text, source: source || "post" }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.level < 2) { care.innerHTML = ""; return; }
        var card = careCard(j.level, j.resources, true).replace("<b>", "<b>Mình thấy bài của bạn có vẻ rất nặng lòng. ");
        care.innerHTML = card; care.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }).catch(function () { /* im lặng: không chặn việc đăng bài */ });
  }
  care.addEventListener("click", function (e) {
    var a = e.target.dataset.act; if (!a) return;
    care.innerHTML = ""; if (a === "ai") open();
  });

  var btn = $("#openAI"); if (btn) btn.addEventListener("click", open);
  window.DualSelf = { open: open, close: close, onPost: onPost };
})();
