"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const openButton = document.getElementById("notification-panel-open");
  if (!openButton) return;
  const panel = document.getElementById("notification-panel");
  const closeButton = document.getElementById("notification-panel-close");
  const heading = document.getElementById("notification-panel-title");
  const backdrop = document.getElementById("notification-backdrop");
  const list = document.getElementById("notification-panel-items");
  const unreadOnly = document.getElementById("notification-unread-only");
  const badge = openButton.querySelector(".app-notification-count");
  let items = [];
  let requestVersion = 0;
  const background = [...document.querySelectorAll(".app-frame, .mobile-nav, .skip-link")];
  let backgroundState = [];

  function render() {
    list.replaceChildren();
    const visible = items.filter((item) => !unreadOnly.checked || !item.read);
    if (!visible.length) {
      const empty = document.createElement("p");
      empty.textContent = unreadOnly.checked ?
        "未読の通知はありません。" : "通知はありません。";
      list.append(empty);
      return;
    }
    for (const item of visible) {
      const article = document.createElement("article");
      article.className = "notification-panel__item";
      const title = document.createElement("h3");
      title.textContent = item.title;
      const body = document.createElement("p");
      body.textContent = item.body;
      const meta = document.createElement("small");
      meta.textContent = item.created_at;
      const states = document.createElement("div");
      states.className = "reference-notification-states";
      const readState = document.createElement("span");
      readState.className = item.read ? "reference-read" : "reference-unread";
      readState.textContent = item.read ? "既読" : "未読";
      const workflow = document.createElement("span");
      workflow.textContent = item.workflow_label;
      states.append(readState, workflow);
      const form = document.createElement("form");
      form.method = "post";
      form.action = item.open_url;
      const csrf = document.createElement("input");
      csrf.type = "hidden";
      csrf.name = "csrfmiddlewaretoken";
      csrf.value = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
      const button = document.createElement("button");
      button.type = "submit";
      button.textContent = "対象画面を開く ›";
      form.append(csrf, button);
      article.append(title, body, meta, states, form);
      list.append(article);
    }
  }

  async function load() {
    const version = ++requestVersion;
    list.textContent = "読み込み中…";
    try {
      const url = new URL(openButton.dataset.panelUrl, window.location.origin);
      if (unreadOnly.checked) url.searchParams.set("status", "unread");
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("通知を取得できませんでした。");
      const data = await response.json();
      if (version !== requestVersion || panel.hidden) return;
      items = data.items;
      const count = data.unread_count;
      openButton.setAttribute("aria-label", `通知${count > 99 ? "99+" : count || ""}（未読${count}件）`);
      if (badge) {
        badge.textContent = count > 99 ? "99+" : String(count);
        badge.hidden = count === 0;
      }
      render();
    } catch (_error) {
      if (version !== requestVersion || panel.hidden) return;
      list.replaceChildren();
      const error = document.createElement("p");
      error.textContent = "通知を読み込めませんでした。";
      const retry = document.createElement("button");
      retry.type = "button";
      retry.textContent = "再試行する";
      retry.addEventListener("click", load);
      list.append(error, retry);
    }
  }

  function show() {
    const mobileMenu = document.querySelector(".mobile-more");
    if (mobileMenu?.open) mobileMenu.open = false;
    panel.hidden = false;
    backdrop.hidden = false;
    openButton.setAttribute("aria-expanded", "true");
    heading.focus();
    backgroundState = background.map((element) => element.inert);
    background.forEach((element) => { element.inert = true; });
    document.body.classList.add("notification-is-open");
    load();
  }

  function hide() {
    ++requestVersion;
    panel.hidden = true;
    backdrop.hidden = true;
    openButton.setAttribute("aria-expanded", "false");
    background.forEach((element, index) => { element.inert = backgroundState[index]; });
    document.body.classList.remove("notification-is-open");
    openButton.focus();
  }

  openButton.addEventListener("click", show);
  closeButton.addEventListener("click", hide);
  backdrop.addEventListener("click", hide);
  unreadOnly.addEventListener("change", load);
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { hide(); return; }
    if (event.key !== "Tab") return;
    const focusable = [...panel.querySelectorAll('button:not([disabled]), a[href], input:not([disabled])')];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === heading)) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); heading.focus();
    }
  });
});
