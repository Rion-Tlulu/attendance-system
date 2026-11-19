"use strict";

/*
 * C03 通知パネル（13・14章）
 * - 新しい順に最大20件。見出し・種別・日時・未読／既読・対応状況を文字で示す。
 * - 読み込み中／通知なし／未読なし／取得失敗と再試行を区別する。
 * - 名称付きモーダル: 見出しへフォーカス、背景は操作対象外、Tab を閉じ込め、Esc で閉じて起点へ戻す。
 */
document.addEventListener("DOMContentLoaded", () => {
  const openButton = document.getElementById("notification-panel-open");
  if (!openButton) return;
  const panel = document.getElementById("notification-panel");
  const closeButton = document.getElementById("notification-panel-close");
  const heading = document.getElementById("notification-panel-title");
  const backdrop = document.getElementById("notification-backdrop");
  const list = document.getElementById("notification-panel-items");
  const status = document.getElementById("notification-panel-status");
  const summary = document.getElementById("notification-panel-summary");
  const filters = [...panel.querySelectorAll('input[name="notification-filter"]')];
  const readAllForm = document.getElementById("notification-read-all-form");
  const readAllButton = readAllForm?.querySelector("button");
  const badge = openButton.querySelector(".app-notification-count");
  const background = [...document.querySelectorAll(".app-frame, .mobile-nav, .skip-link")];
  let items = [];
  let requestVersion = 0;
  let backgroundState = [];

  // 対応状況ごとのアイコン（色だけに頼らず、文字のバッジも併記する）。
  const ICONS = {
    action: "fa-triangle-exclamation",
    done: "fa-circle-check",
    result: "fa-circle-info",
    info: "fa-bell",
  };

  const unreadOnly = () => filters.some((input) => input.checked && input.value === "unread");

  function csrfToken() {
    return readAllForm?.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function icon(name) {
    const node = element("i", `fa-solid ${name}`);
    node.setAttribute("aria-hidden", "true");
    return node;
  }

  function updateCount(count) {
    openButton.setAttribute("aria-label", `通知 未読 ${count} 件`);
    if (badge) {
      badge.textContent = count > 99 ? "99+" : String(count);
      badge.hidden = count === 0;
    }
    summary.textContent = count > 0 ? `未読 ${count > 99 ? "99+" : count} 件` : "未読はありません";
    if (readAllButton) readAllButton.disabled = count === 0;
  }

  function renderItem(item) {
    const key = ICONS[item.workflow_key] ? item.workflow_key : "info";
    const article = element("article", `notice notice--${key}${item.read ? "" : " notice--unread"}`);

    const mark = element("span", "notice__icon");
    mark.append(icon(ICONS[key]));

    const main = element("div", "notice__main");
    const head = element("div", "notice__head");
    const title = element("h3", "notice__title", item.title);
    const states = element("p", "notice__states");
    states.append(
      element("span", item.read ? "notice-badge notice-badge--read" : "notice-badge notice-badge--unread", item.read ? "既読" : "未読"),
      element("span", `notice-badge notice-badge--${key}`, item.workflow_label),
    );
    head.append(title, states);

    const meta = element("p", "notice__meta");
    meta.append(element("span", "notice__kind", item.kind_label || "お知らせ"), element("span", "notice__time", item.created_at));

    const form = element("form", "notice__open-form");
    form.method = "post";
    form.action = item.open_url;
    const csrf = element("input");
    csrf.type = "hidden";
    csrf.name = "csrfmiddlewaretoken";
    csrf.value = csrfToken();
    const button = element("button", "notice__open");
    button.type = "submit";
    button.append(icon("fa-arrow-up-right-from-square"), document.createTextNode(" 対象画面を開く"));
    button.setAttribute("aria-label", `対象画面を開く：${item.title}`);
    form.append(csrf, button);

    main.append(head, meta, form);
    article.append(mark, main);
    return article;
  }

  function render() {
    list.replaceChildren();
    const visible = items.filter((item) => !unreadOnly() || !item.read);
    if (!visible.length) {
      const empty = element("p", "notification-panel__empty");
      empty.append(icon("fa-inbox"), document.createTextNode(unreadOnly() ? " 未読の通知はありません。" : " 通知はありません。"));
      list.append(empty);
      status.textContent = unreadOnly() ? "未読の通知はありません。" : "通知はありません。";
      return;
    }
    list.append(...visible.map(renderItem));
    status.textContent = `${unreadOnly() ? "未読の通知" : "通知"}を${visible.length}件表示しています。`;
  }

  function showError(message) {
    list.replaceChildren();
    const box = element("div", "notification-panel__error");
    box.append(element("p", "", message));
    const retry = element("button", "notification-panel__retry", "再試行する");
    retry.type = "button";
    retry.addEventListener("click", load);
    box.append(retry);
    list.append(box);
    status.textContent = message;
  }

  async function load() {
    const version = ++requestVersion;
    list.replaceChildren(element("p", "notification-panel__loading", "読み込み中…"));
    status.textContent = "通知を読み込んでいます。";
    try {
      const url = new URL(openButton.dataset.panelUrl, window.location.origin);
      if (unreadOnly()) url.searchParams.set("status", "unread");
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("failed");
      const data = await response.json();
      if (version !== requestVersion || panel.hidden) return;
      items = data.items;
      updateCount(data.unread_count);
      render();
    } catch (_error) {
      if (version !== requestVersion || panel.hidden) return;
      // 失敗を0件と表示しない（14章）。
      showError("通知を読み込めませんでした。");
    }
  }

  async function markAllRead(event) {
    event.preventDefault();
    if (!readAllButton || readAllButton.disabled) return;
    readAllButton.disabled = true;
    try {
      const response = await fetch(readAllForm.action, {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json", "X-CSRFToken": csrfToken() },
      });
      if (!response.ok) throw new Error("failed");
      await load();
      status.textContent = "表示中の未読通知を既読にしました。";
    } catch (_error) {
      readAllButton.disabled = false;
      status.textContent = "既読にできませんでした。時間をおいて再試行してください。";
    }
  }

  function focusable() {
    return [...panel.querySelectorAll('button:not([disabled]), a[href], input:not([disabled])')]
      .filter((node) => node.offsetParent !== null);
  }

  function show() {
    const mobileMenu = document.querySelector(".mobile-more");
    if (mobileMenu?.open) mobileMenu.open = false;
    panel.hidden = false;
    backdrop.hidden = false;
    openButton.setAttribute("aria-expanded", "true");
    heading.focus();
    backgroundState = background.map((node) => node.inert);
    background.forEach((node) => { node.inert = true; });
    document.body.classList.add("notification-is-open");
    load();
  }

  function hide() {
    ++requestVersion;
    panel.hidden = true;
    backdrop.hidden = true;
    openButton.setAttribute("aria-expanded", "false");
    background.forEach((node, index) => { node.inert = backgroundState[index]; });
    document.body.classList.remove("notification-is-open");
    openButton.focus();
  }

  openButton.addEventListener("click", show);
  closeButton.addEventListener("click", hide);
  backdrop.addEventListener("click", hide);
  filters.forEach((input) => input.addEventListener("change", load));
  readAllForm?.addEventListener("submit", markAllRead);
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { hide(); return; }
    if (event.key !== "Tab") return;
    const nodes = focusable();
    if (!nodes.length) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === heading)) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); heading.focus();
    }
  });
});
