"""内置网页模板：首页（多目录管理/常用/最近）与 FTP 式浏览页（多选下载/拖拽上传）。

模板使用 __VAR__ 占位符（render() 替换），页面数据经 <script type=application/json> 注入，
避免 str.format 与 JS 花括号转义冲突。无外部依赖，离线可用。
"""

BASE_CSS = """
  :root { --brand:#2563eb; --bg:#f5f6f8; --card:#fff; --text:#1f2328; --muted:#6a737d;
          --border:#e4e7eb; --danger:#dc2626; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
         background:var(--bg); color:var(--text); }
  header { background:var(--card); border-bottom:1px solid var(--border); padding:12px 20px;
           display:flex; flex-wrap:wrap; gap:10px; align-items:center; position:sticky; top:0; z-index:5; }
  header h1 { font-size:18px; margin:0; color:var(--brand); white-space:nowrap; }
  header .sub { color:var(--muted); font-size:13px; }
  .btn { display:inline-block; padding:8px 14px; border:none; border-radius:8px; font-size:14px;
         cursor:pointer; background:var(--brand); color:#fff; }
  .btn.ghost { background:var(--card); color:var(--text); border:1px solid var(--border); }
  .btn.danger { background:var(--danger); }
  .btn:disabled { opacity:.45; cursor:default; }
  dialog { border:none; border-radius:12px; box-shadow:0 12px 40px rgba(0,0,0,.18); padding:20px;
           width:min(560px, 92vw); }
  dialog::backdrop { background:rgba(15,20,30,.45); }
  dialog h3 { margin:0 0 14px; font-size:16px; }
  dialog label { display:block; font-size:13px; color:var(--muted); margin:10px 0 4px; }
  dialog input[type=text] { width:100%; padding:8px 10px; border:1px solid var(--border);
                            border-radius:8px; font-size:14px; }
  dialog .row { display:flex; gap:10px; justify-content:flex-end; margin-top:18px; }
  #toast { position:fixed; left:50%; bottom:28px; transform:translateX(-50%); background:#1f2328;
           color:#fff; padding:10px 18px; border-radius:8px; font-size:14px; opacity:0;
           transition:opacity .25s; pointer-events:none; z-index:99; }
  #toast.show { opacity:.95; }
"""

# ================================================================ 首页

HOME_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LocalShareFile - 共享目录</title>
<style>__CSS__
  main { max-width:1020px; margin:24px auto; padding:0 16px; }
  section { margin-bottom:26px; }
  section h2 { font-size:14px; color:var(--muted); font-weight:500; margin:0 0 10px; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; }
  .chip { background:var(--card); border:1px solid var(--border); border-radius:20px;
          padding:6px 14px; font-size:13px; text-decoration:none; color:var(--text); }
  .chip:hover { border-color:var(--brand); color:var(--brand); }
  .chip b { color:var(--brand); font-weight:600; }
  .cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:12px; }
  .card { position:relative; background:var(--card); border:1px solid var(--border); border-radius:12px;
          padding:16px; text-decoration:none; color:var(--text); display:block;
          transition:box-shadow .15s, transform .15s; }
  .card:hover { box-shadow:0 4px 14px rgba(0,0,0,.1); transform:translateY(-1px); }
  .card .t { display:flex; align-items:center; gap:8px; font-size:16px; font-weight:600;
             word-break:break-all; padding-right:22px; }
  .card .p { color:var(--muted); font-size:12px; margin-top:6px; word-break:break-all;
             display:block; }
  .card .n { color:var(--brand); font-size:12px; margin-top:8px; }
  .card .del { position:absolute; top:10px; right:10px; border:none; background:none; cursor:pointer;
               color:var(--muted); font-size:14px; line-height:1; padding:4px; border-radius:6px; }
  .card .del:hover { color:var(--danger); background:#fee2e2; }
  .empty { color:var(--muted); font-size:14px; background:var(--card); border:1px dashed var(--border);
           border-radius:12px; padding:34px; text-align:center; }
  ul.recent { list-style:none; margin:0; padding:0; }
  ul.recent li { background:var(--card); border:1px solid var(--border); border-radius:10px;
                 padding:10px 14px; margin-bottom:8px; font-size:14px;
                 display:flex; justify-content:space-between; gap:10px; }
  ul.recent a { color:var(--text); text-decoration:none; word-break:break-all; }
  ul.recent a:hover { color:var(--brand); }
  ul.recent span { color:var(--muted); font-size:12px; white-space:nowrap; }
  #pickList div { padding:8px 10px; border-radius:8px; cursor:pointer; font-size:14px; }
  #pickList div:hover { background:var(--bg); color:var(--brand); }
  #pickCrumbs { font-size:13px; color:var(--muted); padding:8px 0; word-break:break-all; }
  #pickCrumbs .crumb { color:var(--brand); cursor:pointer; margin-right:4px; }
</style>
</head>
<body>
<header>
  <h1>📂 LocalShareFile</h1>
  <span class="sub">局域网文件共享 · v__VERSION__</span>
  <span style="flex:1"></span>
  <button class="btn" onclick="addDlg.showModal()">➕ 添加共享目录</button>
</header>
<main>
  <section>
    <h2>🔥 常用目录（按访问次数）</h2>
    <div class="chips">__TOP_CHIPS__</div>
  </section>
  <section>
    <h2>📁 共享目录（__DIR_COUNT__ 个）</h2>
    <div class="cards">__DIR_CARDS__</div>
  </section>
  <section>
    <h2>🕘 最近访问</h2>
    __RECENT__
  </section>
</main>

<dialog id="addDlg">
  <h3>添加共享目录</h3>
  <label>显示名称（留空则使用目录名）</label>
  <input type="text" id="addName" placeholder="例如：电影库">
  <label>服务器上的目录路径</label>
  <input type="text" id="addPath" placeholder="例如 /data/movies 或 ~/documents">
  <div class="row">
    <button class="btn ghost" onclick="addDlg.close()">取消</button>
    <button class="btn ghost" onclick="openPicker()">📁 浏览服务器目录</button>
    <button class="btn" onclick="submitAdd()">添加</button>
  </div>
</dialog>

<dialog id="pickDlg">
  <h3>选择服务器目录 <span class="sub" style="color:var(--muted);font-size:12px"></span></h3>
  <div id="pickCrumbs"></div>
  <div id="pickList" style="min-height:120px; max-height:46vh; overflow:auto;
       border:1px solid var(--border); border-radius:8px; margin-top:6px"></div>
  <label>手动输入路径</label>
  <input type="text" id="pickManual" placeholder="/absolute/path" onkeydown="if(event.key==='Enter')loadBrowse(this.value)">
  <div class="row">
    <button class="btn ghost" onclick="pickDlg.close()">返回</button>
    <button class="btn" onclick="chooseCur()">✅ 选定当前目录</button>
  </div>
</dialog>

<div id="toast"></div>
<script id="lsf-data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('lsf-data').textContent);
const toast = (msg) => {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2600);
};
async function api(url, opt) {
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || ('HTTP ' + r.status));
  return r.json();
}
async function submitAdd() {
  try {
    const res = await api('/api/dirs', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: addName.value.trim(), path: addPath.value.trim()})
    });
    toast(res.message); addDlg.close();
    setTimeout(() => location.reload(), 500);
  } catch (e) { toast('❌ ' + e.message); }
}
async function delDir(name) {
  if (!confirm('确定移除共享目录「' + name + '」？\\n（只取消共享，不会删除服务器上的文件）')) return;
  try {
    const res = await api('/api/dirs/' + encodeURIComponent(name), {method: 'DELETE'});
    toast(res.message);
    setTimeout(() => location.reload(), 500);
  } catch (e) { toast('❌ ' + e.message); }
}
/* ---- 服务器目录选择器 ---- */
let curPath = '';
const esc = s => String(s).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function loadBrowse(p) {
  try {
    const st = await api('/api/browse?path=' + encodeURIComponent(p || '/'));
    curPath = st.path;
    pickManual.value = curPath;
    pickCrumbs.innerHTML = st.crumbs.map(c => `<span class="crumb" data-p="${esc(c.path)}">${esc(c.name)}／</span>`).join('');
    pickCrumbs.querySelectorAll('.crumb').forEach(el => el.onclick = () => loadBrowse(el.dataset.p));
    pickList.innerHTML = st.dirs.length
      ? st.dirs.map(d => `<div class="pickrow" data-p="${esc((curPath.replace(/\\/+$/, '')) + '/' + d)}">📁 ${esc(d)}</div>`).join('')
      : '<div style="color:var(--muted);padding:14px">（没有子目录）</div>';
    pickList.querySelectorAll('.pickrow').forEach(el => el.onclick = () => loadBrowse(el.dataset.p));
  } catch (e) { toast('❌ ' + e.message); }
}
function openPicker() { pickDlg.showModal(); loadBrowse(curPath || DATA.home); }
function chooseCur() { addPath.value = curPath; pickDlg.close(); addDlg.showModal(); }
</script>
</body>
</html>
"""

# ================================================================ 浏览页（FTP 风格）

BROWSE_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ - LocalShareFile</title>
<style>__CSS__
  main { max-width:1080px; margin:18px auto; padding:0 16px; }
  .crumbs { flex:1; min-width:180px; font-size:14px; overflow:hidden; text-overflow:ellipsis;
            white-space:nowrap; }
  .crumbs a { color:var(--brand); text-decoration:none; }
  select { padding:8px 10px; border:1px solid var(--border); border-radius:8px; font-size:13px;
           background:var(--card); max-width:230px; }
  table { width:100%; border-collapse:collapse; background:var(--card); border-radius:10px;
          overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.06); }
  th,td { padding:9px 12px; text-align:left; font-size:14px; border-bottom:1px solid var(--border); }
  th { color:var(--muted); font-weight:500; font-size:13px; }
  tr:last-child td { border-bottom:none; }
  td.name { word-break:break-all; }
  td.name a { color:var(--text); text-decoration:none; display:flex; align-items:center; gap:8px; }
  td.name a:hover { color:var(--brand); }
  td.op a, td.op button.linkish { color:var(--brand); text-decoration:none; margin-right:10px;
      font-size:13px; background:none; border:none; cursor:pointer; padding:0; font-family:inherit; }
  .muted { color:var(--muted); }
  tr.rowdir.over { background:#eff6ff; outline:2px dashed var(--brand); outline-offset:-2px; }
  .icon { width:19px; height:19px; flex:none; }
  #dropmask { display:none; position:fixed; inset:0; background:rgba(37,99,235,.12);
      border:3px dashed var(--brand); z-index:9; font-size:20px; color:var(--brand);
      align-items:center; justify-content:center; }
  body.dragging #dropmask { display:flex; }
  #prog { display:none; margin-top:10px; background:var(--card); border-radius:8px; padding:10px 14px;
      font-size:13px; box-shadow:0 1px 3px rgba(0,0,0,.06); }
  #bar { height:6px; background:var(--border); border-radius:3px; margin-top:6px; overflow:hidden; }
  #bar>div { height:100%; width:0; background:var(--brand); transition:width .15s; }
  footer { text-align:center; color:var(--muted); font-size:12px; margin:28px 0; }
</style>
</head>
<body>
<header>
  <a class="btn ghost" href="/" style="text-decoration:none">🏠 首页</a>
  <nav class="crumbs">__CRUMBS__</nav>
  <select id="hist" title="历史目录">
    <option value="">🕘 历史目录…</option>
    __HIST_OPTIONS__
  </select>
  <button class="btn ghost" id="selBtn" disabled onclick="downloadSel()">⬇ 下载选中 (<span id=selN>0</span>)</button>
  <button class="btn" id="pick" __UPLOAD_DISABLED__>⬆ 上传</button>
  <input id="file" type="file" multiple hidden __UPLOAD_DISABLED__>
</header>
<main>
  <div class="toolbar" style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap">
    <input id="q" type="search" placeholder="筛选当前目录…" style="flex:1;min-width:150px;
           padding:9px 12px;border:1px solid var(--border);border-radius:8px;font-size:14px;outline:none">
    <span class="muted" style="font-size:13px;align-self:center" id="stat">__STAT__</span>
    <span class="muted" style="font-size:13px;align-self:center">__UPLOAD_STATE__</span>
  </div>
  <table>
    <thead><tr>
      <th style="width:34px"><input type="checkbox" id="all" onchange="toggleAll(this.checked)"></th>
      <th style="width:52%">名称</th><th>大小</th><th>修改时间</th><th>操作</th>
    </tr></thead>
    <tbody>__ROWS__</tbody>
  </table>
  <div id="prog"><span id="ptext"></span><div id="bar"><div></div></div></div>
</main>
<div id="dropmask">松开鼠标即可上传到当前目录</div>
<footer>LocalShareFile v__VERSION__ · 仅限可信局域网内使用</footer>
<script id="lsf-data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('lsf-data').textContent);
const CUR = DATA.rel;                        // 当前目录相对路径（空串=共享根）
const rows = [...document.querySelectorAll('tbody tr')];
document.getElementById('q').addEventListener('input', e => {
  const k = e.target.value.trim().toLowerCase();
  rows.forEach(r => r.style.display = !k || r.dataset.n.indexOf(k) >= 0 ? '' : 'none');
});
document.getElementById('hist').addEventListener('change', e => {
  if (e.target.value) location.href = e.target.value;
});
/* ---- 多选 ---- */
function checkedPaths() {
  return [...document.querySelectorAll('tbody input[type=checkbox]:checked')]
    .map(c => c.value);
}
 function refreshSel() { selN.textContent = checkedPaths().length; selBtn.disabled = !checkedPaths().length; }
function toggleAll(on) {
  rows.forEach(r => { if (r.style.display !== 'none') r.querySelector('input').checked = on; });
  refreshSel();
}
document.addEventListener('change', e => { if (e.target.matches('tbody input[type=checkbox]')) refreshSel(); });
function postZip(paths) {
  const f = document.createElement('form');
  f.method = 'POST'; f.action = '/zip';
  paths.forEach(p => {
    const i = document.createElement('input');
    i.name = 'p'; i.value = p; f.appendChild(i);
  });
  document.body.appendChild(f); f.submit(); f.remove();
}
function downloadSel() { postZip(checkedPaths()); }
function downloadOne(path) { postZip([path]); }
/* ---- 上传（拖到页面=当前目录；拖到目录行=该目录） ---- */
function uploadOne(file, dir, done) {
  const xhr = new XMLHttpRequest();
  xhr.open('PUT', '/upload?dir=' + encodeURIComponent(DATA.share + (dir ? '/' + dir : '')) +
           '&name=' + encodeURIComponent(file.name));
  xhr.upload.onprogress = e => {
    if (e.lengthComputable) {
      const pct = Math.round(e.loaded / e.total * 100);
      ptext.textContent = `上传 ${file.name} → ${dir || '当前目录'} … ${pct}%`;
      bar.firstElementChild.style.width = pct + '%';
    }
  };
  xhr.onload = () => done(xhr.status >= 200 && xhr.status < 300);
  xhr.onerror = () => done(false);
  xhr.send(file);
}
function uploadFiles(list, dir) {
  const files = [...list]; if (!files.length) return;
  prog.style.display = 'block'; pick.disabled = true;
  let ok = 0;
  (function next() {
    if (!files.length) {
      ptext.textContent = ok ? `✅ 上传完成（${ok} 个文件），正在刷新…` : '❌ 上传失败（详见服务端日志）';
      setTimeout(() => location.reload(), 800);
      return;
    }
    uploadOne(files.shift(), dir || CUR, succeeded => { if (succeeded) ok++; next(); });
  })();
}
document.getElementById('pick').addEventListener('click', () => file.click());
document.getElementById('file').addEventListener('change', e => uploadFiles(e.target.files));
document.addEventListener('dragover', e => { e.preventDefault(); document.body.classList.add('dragging'); });
document.addEventListener('dragleave', e => { if (!e.relatedTarget) document.body.classList.remove('dragging'); });
document.addEventListener('drop', e => {
  e.preventDefault(); document.body.classList.remove('dragging');
  if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files, CUR);
});
/* 拖拽到目录行：上传到该目录 */
document.querySelectorAll('tr.rowdir').forEach(tr => {
  const dir = tr.dataset.dir;
  tr.addEventListener('dragenter', () => tr.classList.add('over'));
  tr.addEventListener('dragover', e => e.preventDefault());
  tr.addEventListener('dragleave', () => tr.classList.remove('over'));
  tr.addEventListener('drop', e => {
    e.preventDefault(); e.stopPropagation(); tr.classList.remove('over');
    document.body.classList.remove('dragging');
    if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files, dir);
  });
});
</script>
</body>
</html>
"""

ICON_DIR = """<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="1.8">
<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>"""

ICON_FILE = """<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="#6a737d" stroke-width="1.8">
<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"/>
<path d="M14 3v5h5"/></svg>"""


def render(template: str, **replacements) -> str:
    """用 __KEY__ 占位符替换渲染模板。"""
    out = template
    for key, value in replacements.items():
        out = out.replace(f"__{key.upper()}__", str(value))
    return out


def json_script(data) -> str:
    """把数据安全序列化为可内嵌 <script type=application/json> 的文本。"""
    import json
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
