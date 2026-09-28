const title = document.getElementById("statusTitle");
const message = document.getElementById("statusMessage");
const detail = document.getElementById("statusDetail");
const dot = document.getElementById("statusDot");
const actions = document.getElementById("failureActions");
const retry = document.getElementById("retryButton");

function renderStatus(status) {
  const failed = status.phase === "failed";
  title.textContent = failed ? "后台未能启动" : status.phase === "ready" ? "工作区已就绪" : "正在准备工作区";
  message.textContent = status.message || "正在检查漫画流水线后台...";
  detail.textContent = status.detail || "";
  detail.classList.toggle("hidden", !status.detail);
  dot.classList.toggle("failed", failed);
  dot.classList.toggle("running", !failed && status.phase !== "ready");
  actions.classList.toggle("hidden", !failed);
  retry.disabled = false;
}

window.comicDesktop.onStartupStatus(renderStatus);
window.comicDesktop.getInfo().then((info) => {
  document.getElementById("runtimeLabel").textContent = `Windows 桌面版 ${info.version}`;
});
retry.addEventListener("click", async () => {
  retry.disabled = true;
  renderStatus({ phase: "checking", message: "正在重新检查后台..." });
  await window.comicDesktop.retryStartup();
});
document.getElementById("logButton").addEventListener("click", () => window.comicDesktop.openLog());
