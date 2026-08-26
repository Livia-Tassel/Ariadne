const choose = document.getElementById("choose-project");
const message = document.getElementById("message");
const recentSection = document.getElementById("recent-section");
const recentList = document.getElementById("recent-list");

const esc = (value = "") => String(value)
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

function showMessage(text) {
  message.textContent = text;
  message.hidden = !text;
}

function setBusy(busy) {
  choose.disabled = busy;
  choose.querySelector("strong").textContent = busy ? "正在打开…" : "选择研究目录";
}

async function selectProject() {
  showMessage(""); setBusy(true);
  try {
    const result = await window.pywebview.api.choose_project();
    if (!result.ok && !result.cancelled) showMessage(result.error || "无法打开这个目录");
  } catch (error) { showMessage(String(error)); }
  finally { setBusy(false); }
}

async function openRecent(path, button) {
  button.disabled = true; showMessage("");
  try {
    const result = await window.pywebview.api.open_recent(path);
    if (!result.ok) showMessage(result.error || "无法打开这个项目");
  } catch (error) { showMessage(String(error)); }
  finally { button.disabled = false; }
}

function renderRecent(projects) {
  recentSection.hidden = !projects.length;
  recentList.innerHTML = projects.map(project => `<button class="recent-project" data-path="${esc(project.path)}"><span>⌂</span><div><strong>${esc(project.name)}</strong><small>${esc(project.path)}</small></div><b>→</b></button>`).join("");
  recentList.querySelectorAll(".recent-project").forEach(button => {
    button.addEventListener("click", () => openRecent(button.dataset.path, button));
  });
}

async function bootstrap() {
  try {
    const result = await window.pywebview.api.bootstrap();
    renderRecent(result.recent_projects || []);
  } catch (error) { showMessage("桌面组件没有正确初始化：" + error); }
}

choose.addEventListener("click", selectProject);
window.addEventListener("pywebviewready", bootstrap);
