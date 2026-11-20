"use strict";

/* ==============================================
   スマートフォン：ヘッダーの「メニュー」で同じ階層を開く
============================================== */
document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.querySelector(".app-menu-toggle");
  const side = document.getElementById("app-side");
  const backdrop = document.querySelector(".app-side-backdrop");
  if (!toggle || !side) return;
  const mobile = window.matchMedia("(max-width: 860px)");
  const background = [...document.querySelectorAll(".app-content, .app-topbar")];

  function setInert(value) {
    background.forEach((node) => { node.inert = value; });
  }

  function close(returnFocus = true) {
    if (!side.classList.contains("is-open")) return;
    side.classList.remove("is-open");
    if (backdrop) backdrop.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    document.body.classList.remove("menu-is-open");
    setInert(false);
    if (returnFocus) toggle.focus();
  }

  function open() {
    side.classList.add("is-open");
    if (backdrop) backdrop.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    document.body.classList.add("menu-is-open");
    setInert(true);
    (side.querySelector("[aria-current='page']") || side.querySelector("summary, a"))?.focus();
  }

  toggle.addEventListener("click", () => {
    if (side.classList.contains("is-open")) close();
    else open();
  });
  document.querySelectorAll("[data-side-close]").forEach((node) => node.addEventListener("click", () => close()));
  side.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { close(); return; }
    if (event.key !== "Tab" || !side.classList.contains("is-open")) return;
    const nodes = [...side.querySelectorAll("button, summary, a[href]")].filter((node) => node.offsetParent !== null);
    if (!nodes.length) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  mobile.addEventListener("change", () => close(false));
  // 通知パネルを開く前にメニューを閉じ、同時に二つのパネルを操作対象にしない。
  document.addEventListener("app:close-menu", () => close(false));
});

/* ==============================================
   入力エラーの要約（エラー項目へのリンク）
============================================== */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form").forEach((form) => {
    const errors = [...form.querySelectorAll("ul.errorlist")];
    if (!errors.length) return;
    const summary = document.createElement("div");
    summary.className = "form-error-summary";
    summary.setAttribute("role", "alert");
    const heading = document.createElement("strong");
    heading.textContent = "入力内容を確認してください。";
    const list = document.createElement("ul");
    summary.append(heading, list);

    errors.forEach((error, index) => {
      const message = error.textContent.trim();
      if (!message) return;
      error.id ||= `form-error-${index}-${Math.random().toString(36).slice(2, 8)}`;
      const wrapper = error.closest(".field, .form-row, .break-form, fieldset") || error.parentElement;
      const field = wrapper.querySelector("input:not([type=hidden]), select, textarea");
      const item = document.createElement("li");
      if (field && field.form === form) {
        field.id ||= `form-field-${index}-${Math.random().toString(36).slice(2, 8)}`;
        field.setAttribute("aria-invalid", "true");
        const describedBy = new Set((field.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
        describedBy.add(error.id);
        field.setAttribute("aria-describedby", [...describedBy].join(" "));
        const label = form.querySelector(`label[for="${CSS.escape(field.id)}"]`);
        const link = document.createElement("a");
        link.href = `#${field.id}`;
        link.textContent = `${label?.textContent.trim() || field.name}: ${message}`;
        item.append(link);
      } else {
        item.textContent = message;
      }
      list.append(item);
    });
    form.prepend(summary);
  });
});

/* ==============================================
   パスワードの「表示する／隠す」
============================================== */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-toggle-password]").forEach((button) => {
    const input = document.getElementById(button.dataset.togglePassword);
    if (!input) return;
    button.addEventListener("click", () => {
      const isVisible = input.type === "text";
      input.type = isVisible ? "password" : "text";
      const icon = button.querySelector("i");
      button.textContent = "";
      if (icon) {
        icon.className = isVisible ? "fa-regular fa-eye" : "fa-regular fa-eye-slash";
        button.append(icon, " ");
      }
      button.append(isVisible ? "表示する" : "隠す");
      button.setAttribute("aria-pressed", String(!isVisible));
    });
  });

  // 初回変更画面のチェックボックス型「表示する」
  document.querySelectorAll("[data-show-password]").forEach((checkbox) => {
    const input = document.getElementById(checkbox.dataset.showPassword);
    if (!input) return;
    checkbox.addEventListener("change", () => {
      input.type = checkbox.checked ? "text" : "password";
    });
  });
});

/* ==============================================
   E06 業務管理者の権限管理：変更内容の確認
============================================== */
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("reference-role-form");
  if (!form) return;
  const preview = document.querySelector("[data-role-preview]");
  const submit = document.querySelector("[data-role-submit]");
  const result = document.querySelector("[data-role-result]");
  const status = document.querySelector("[data-role-preview-status]");
  preview?.addEventListener("click", () => {
    if (!form.reportValidity()) return;
    const granting = new FormData(form).get("desired_role") === "admin";
    if (result) result.textContent = granting ? `${result.dataset.current} → 業務管理者` : `${result.dataset.current} → 一般社員`;
    submit.textContent = granting ? "管理権限を付与する" : "管理権限を取り消す";
    submit.hidden = false;
    preview.hidden = true;
    if (status) status.textContent = "対象社員と変更理由を確認してから確定してください。";
    submit.focus();
  });
  form.addEventListener("input", () => {
    if (!submit) return;
    submit.hidden = true;
    if (preview) preview.hidden = false;
    if (status) status.textContent = "入力が変わりました。変更内容を再確認してください。";
  });
});

/* ==============================================
   E01 打刻：時計表示と二重送信防止
============================================== */
document.addEventListener("DOMContentLoaded", () => {
  const element = document.getElementById("e01-current-time");
  if (element) {
    const initialTime = Date.parse(element.dataset.serverTime);
    if (Number.isFinite(initialTime)) {
      const startedAt = performance.now();
      const formatter = new Intl.DateTimeFormat("ja-JP", {
        timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
      });
      const update = () => { element.textContent = formatter.format(new Date(initialTime + performance.now() - startedAt)); };
      update();
      const interval = setInterval(update, 1000);
      window.addEventListener("pagehide", () => clearInterval(interval), { once: true });
    }
  }

  let submitting = false;
  const forms = [...document.querySelectorAll(".clock-form")];
  forms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (submitting) {
        event.preventDefault();
        return;
      }
      submitting = true;
      forms.forEach((otherForm) => {
        const button = otherForm.querySelector('button[type="submit"]');
        if (!button) return;
        button.disabled = true;
        if (otherForm === form) button.textContent = "記録中…";
      });
    });
  });

  // ブラウザの戻る操作等で無効状態が残った際は画面を再取得する。
  if (forms.length) {
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) window.location.reload();
    });
  }
});

/* ==============================================
   画面 07・24：対象ごとの操作（変更しない／変更／追加／取消）
   「変更」「追加」のときだけ変更後の日時を編集できるようにする。
============================================== */
function initOpCard(card) {
  const radios = [...card.querySelectorAll('input[type="radio"]')];
  const inputs = [...card.querySelectorAll('.op-card__after input:not([type="hidden"])')];
  card.dataset.opReady = "1";
  inputs.forEach((input) => { input.dataset.original = input.value; });
  const apply = (focus) => {
    const checked = radios.find((radio) => radio.checked);
    const operation = checked ? checked.value : "add";
    const editable = operation === "change" || operation === "add";
    card.classList.toggle("is-active", editable);
    card.classList.toggle("is-cancel", operation === "cancel");
    inputs.forEach((input) => {
      input.readOnly = !editable;
      input.setAttribute("aria-readonly", String(!editable));
      if (operation === "keep") input.value = input.dataset.original;
    });
    if (focus && editable) inputs[0]?.focus();
  };
  radios.forEach((radio) => radio.addEventListener("change", () => apply(true)));
  apply(false);
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-op-card]").forEach(initOpCard);
});

/* ==============================================
   E03・代理申請：休憩の追加
============================================== */
document.addEventListener("DOMContentLoaded", () => {
  const addButton = document.querySelector("[data-e03-add-break]");
  const list = document.getElementById("e03-break-form-list");
  const template = document.getElementById("e03-empty-break-template");
  const totalForms = document.querySelector('input[name="breaks-TOTAL_FORMS"]');
  const maxForms = document.querySelector('input[name="breaks-MAX_NUM_FORMS"]');
  if (!addButton || !list || !template || !totalForms) return;

  const configuredMax = Number.parseInt(maxForms?.value || "20", 10);
  const maximum = Math.min(Number.isFinite(configuredMax) ? configuredMax : 20, 20);
  const updateButton = () => {
    addButton.disabled = Number.parseInt(totalForms.value, 10) >= maximum;
  };

  addButton.addEventListener("click", () => {
    const current = Number.parseInt(totalForms.value, 10);
    if (!Number.isFinite(current) || current >= maximum) return;
    // 表の中に追加する場合は tbody で解釈しないと tr が失われる。
    const wrapper = document.createElement(list.tagName === "TBODY" ? "tbody" : "div");
    wrapper.innerHTML = template.innerHTML.replaceAll("__prefix__", String(current)).trim();
    const newRow = wrapper.firstElementChild;
    if (!newRow) return;
    const heading = newRow.querySelector(".op-row__title, h3");
    if (heading) heading.textContent = `休憩（追加 ${current + 1}）`;
    initOpCard(newRow);
    list.appendChild(newRow);
    totalForms.value = String(current + 1);
    updateButton();
    newRow.querySelector("input:not([type='hidden']):not([type='checkbox']):not([type='radio'])")?.focus();
  });

  updateButton();
});

/* ==============================================
   F11 勤怠グラフ（E02 / A01 / A04 共通）
============================================== */
(() => {
  function initF11Chart(root) {
    const showButton = root.querySelector("[data-f11-show]");
    const hideButton = root.querySelector("[data-f11-hide]");
    const table = root.querySelector("[data-f11-table]");
    const panel = root.querySelector("[data-f11-panel]");
    const canvas = root.querySelector("[data-f11-canvas]");
    const message = root.querySelector("[data-f11-message]");
    const heading = panel?.querySelector("h2");
    const jsonElement = root.querySelector('script[type="application/json"]');
    const linkedTable = document.getElementById(root.dataset.f11LinkedTable || "");
    if (!showButton || !panel || !canvas || !message || !jsonElement) return;

    let instance = null;
    let graphData = null;

    function notify(text) {
      message.textContent = text;
      message.hidden = false;
    }

    function clearNotice() {
      message.textContent = "";
      message.hidden = true;
    }

    function displayTable(moveFocus = false) {
      if (table && !linkedTable) table.hidden = false;
      if (linkedTable) linkedTable.hidden = false;
      panel.hidden = true;
      showButton.hidden = false;
      showButton.setAttribute("aria-expanded", "false");
      if (moveFocus) showButton.focus();
    }

    function parseData() {
      try {
        const parsed = JSON.parse(jsonElement.textContent);
        if (!parsed || !Array.isArray(parsed.rows)) return null;
        const valid = parsed.rows.every((row) => row.value === null
          || (typeof row.value === "number" && Number.isFinite(row.value) && row.value >= 0));
        return valid ? parsed : null;
      } catch (_error) {
        return null;
      }
    }

    function reducedMotion() {
      return typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    function createChart(data) {
      return new window.Chart(canvas, {
        type: "bar",
        data: {
          labels: data.rows.map((row) => row.label),
          datasets: [{
            label: data.title,
            data: data.rows.map((row) => row.value),
            backgroundColor: "#1f5a3f",
            borderColor: "#123f2b",
            borderWidth: 1,
            maxBarThickness: 22,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: reducedMotion() ? false : { duration: 250 },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label(context) {
                  const row = data.rows[context.dataIndex];
                  return row ? row.display : "";
                },
              },
            },
          },
          scales: {
            x: { grid: { display: false }, ticks: { autoSkip: true, maxTicksLimit: 8 } },
            y: {
              beginAtZero: true,
              grid: { color: "#e2e2dc" },
              ticks: data.kind === "incomplete_count" ? { precision: 0 } : {},
            },
          },
        },
      });
    }

    function displayGraph(moveFocus = false) {
      clearNotice();
      if (typeof window.Chart !== "function") {
        displayTable();
        notify("グラフを読み込めませんでした。数値表は引き続き利用できます。");
        return;
      }
      if (graphData === null) graphData = parseData();
      if (graphData === null) {
        displayTable();
        notify("グラフ用データの読み込みに失敗しました。数値表をご確認ください。");
        return;
      }
      if (!graphData.rows.some((row) => row.value !== null)) {
        displayTable();
        notify("対象期間にグラフで表示できる完了記録がありません。勤務状態は数値表で確認できます。");
        return;
      }
      panel.hidden = false;
      try {
        if (instance === null) instance = createChart(graphData);
        else instance.resize();
        if (table) table.hidden = true;
        if (linkedTable) linkedTable.hidden = true;
        showButton.hidden = true;
        showButton.setAttribute("aria-expanded", "true");
        if (moveFocus) heading?.focus();
      } catch (_error) {
        if (instance !== null) {
          instance.destroy();
          instance = null;
        }
        displayTable();
        notify("グラフの描画に失敗しました。数値表は引き続き確認できます。");
      }
    }

    showButton.addEventListener("click", () => displayGraph(true));
    hideButton?.addEventListener("click", () => {
      clearNotice();
      displayTable(true);
    });

    if (root.dataset.f11Default === "graph") displayGraph();
    else displayTable();
  }

  function initialize() {
    document.querySelectorAll("[data-f11-chart]").forEach(initF11Chart);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();

/* ==============================================
   ページ内リンクの移動先が閉じた details なら開く
============================================== */
(() => {
  function openTarget(hash) {
    if (!hash || hash.length < 2) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    const details = target?.closest("details");
    if (details && !details.open) details.open = true;
  }
  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (link) openTarget(link.getAttribute("href"));
  });
  window.addEventListener("hashchange", () => openTarget(window.location.hash));
  document.addEventListener("DOMContentLoaded", () => openTarget(window.location.hash));
})();

/* ==============================================
   A07 部署登録：最初の社員番号の例
============================================== */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-code-example-for]").forEach((box) => {
    const select = document.getElementById(box.dataset.codeExampleFor);
    const output = box.querySelector("output");
    if (!select || !output) return;
    const update = () => { output.textContent = select.value ? `${select.value}0001` : "—"; };
    select.addEventListener("change", update);
    update();
  });
});
