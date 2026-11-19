/* ---- static/js/auth.js ---- */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('[role="tablist"]').forEach((list) => {
    const tabs = [...list.querySelectorAll("[data-reference-tab]")];
    function select(tab) {
      tabs.forEach((item) => {
        const selected = item === tab;
        item.setAttribute("aria-selected", String(selected));
        item.tabIndex = selected ? 0 : -1;
        const panel = document.getElementById(item.getAttribute("aria-controls"));
        if (panel) panel.hidden = !selected;
      });
    }
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => select(tab));
      tab.addEventListener("keydown", (event) => {
        let next;
        if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
        else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = tabs.length - 1;
        else return;
        event.preventDefault(); select(tabs[next]); tabs[next].focus();
      });
    });
  });
  const form = document.getElementById("reference-role-form");
  if (!form) return;
  const preview = document.querySelector("[data-role-preview]");
  const submit = document.querySelector("[data-role-submit]");
  const result = document.querySelector("[data-role-result]");
  const status = document.querySelector("[data-role-preview-status]");
  preview?.addEventListener("click", () => {
    if (!form.reportValidity()) return;
    const granting = new FormData(form).get("desired_role") === "admin";
    result.textContent = granting ? "管理権限を付与する" : "管理権限を取り消す";
    submit.textContent = result.textContent;
    submit.hidden = false;
    status.textContent = "対象社員と変更理由を確認してから確定してください。";
    submit.focus();
  });
  form.addEventListener("input", () => {
    submit.hidden = true; status.textContent = "入力が変わりました。変更内容を再確認してください。";
  });
});

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
      const wrapper = error.closest(
        ".admin-field, .v2-field, .field, .form-group, fieldset"
      ) || error.parentElement;
      const field = wrapper.querySelector(
        "input:not([type=hidden]), select, textarea"
      );
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

document.addEventListener("DOMContentLoaded", () => {
  const menu = document.querySelector(".mobile-more");
  if (!menu) return;
  const headerButton = document.querySelector(".app-menu-toggle");
  const summary = menu.querySelector("summary");
  let origin = summary;
  summary?.addEventListener("click", () => { origin = summary; });
  headerButton?.addEventListener("click", () => {
    origin = headerButton;
    menu.open = !menu.open;
    if (menu.open) menu.querySelector(".mobile-more-panel button, .mobile-more-panel a")?.focus();
  });
  menu.addEventListener("toggle", () => {
    headerButton?.setAttribute("aria-expanded", String(menu.open));
  });
  menu.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !menu.open) return;
    menu.open = false;
    origin?.focus();
  });
  menu.querySelectorAll("[data-mobile-section]").forEach((button) => {
    button.addEventListener("click", () => {
      const section = document.getElementById(button.getAttribute("aria-controls"));
      if (!section) return;
      section.hidden = !section.hidden;
      button.setAttribute("aria-expanded", String(!section.hidden));
    });
  });
});

document.addEventListener("DOMContentLoaded", () => {
  const toggleButtons = document.querySelectorAll("[data-toggle-password]");

  toggleButtons.forEach((button) => {
    const inputId = button.dataset.togglePassword;
    const input = document.getElementById(inputId);

    if (!input) {
      return;
    }

    button.addEventListener("click", () => {
      const isVisible = input.type === "text";

      input.type = isVisible ? "password" : "text";

      // 画面設計（C01・C02）に合わせ「表示する／隠す」とし、目のアイコンを保持する。
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
});

/* ---- static/js/clock.js ---- */
("use strict");

document.addEventListener("DOMContentLoaded", () => {
  // 日付と時刻は表示用。打刻時刻はDjangoサーバーで決定する。
  const dateElement = document.getElementById("current-date");
  const clockElement = document.getElementById("current-clock");
  const dateFormatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  });
  const timeFormatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  const renderClock = () => {
    const now = new Date();
    if (dateElement) dateElement.textContent = dateFormatter.format(now);
    if (clockElement) clockElement.textContent = timeFormatter.format(now);
  };
  renderClock();
  if (dateElement || clockElement) window.setInterval(renderClock, 1000);

  let submitting = false;
  const forms = [...document.querySelectorAll(".clock-form")];
  forms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (submitting) {
        event.preventDefault();
        return;
      }
      submitting = true;
      // 同じページの他の打刻操作も押せないようにする。
      forms.forEach((otherForm) => {
        const button = otherForm.querySelector('button[type="submit"]');
        if (!button) return;
        button.disabled = true;
        if (otherForm === form) {
          button.textContent = "記録中…";
        }
      });
    });
  });

  // ブラウザの戻る操作等で無効状態が残った際は画面を再取得する。
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });
});

/* ---- static/js/e01-clock-display.js ---- */
("use strict");

/**
 * E01 打刻ホーム
 * 表示用の日本時間時計
 *
 * サーバーから渡された表示時刻を基準にする。
 * 実際の打刻時刻はDjango側で決定する。
 */

document.addEventListener("DOMContentLoaded", () => {
  const element = document.getElementById("e01-current-time");

  if (!element) {
    return;
  }

  const rawTime = element.dataset.serverTime;
  const initialTime = Date.parse(rawTime);

  if (!Number.isFinite(initialTime)) {
    return;
  }

  const startedAt = performance.now();

  const formatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });

  const update = () => {
    const elapsed = performance.now() - startedAt;

    const current = new Date(initialTime + elapsed);

    element.textContent = formatter.format(current);
  };

  update();

  const interval = setInterval(update, 1000);

  window.addEventListener(
    "pagehide",
    () => {
      clearInterval(interval);
    },
    { once: true },
  );
});

/* ---- static/js/e03-breaks.js ---- */
("use strict");

document.addEventListener("DOMContentLoaded", () => {
  const addButton = document.querySelector("[data-e03-add-break]");

  const list = document.getElementById("e03-break-form-list");

  const template = document.getElementById("e03-empty-break-template");

  const totalForms = document.querySelector('input[name="breaks-TOTAL_FORMS"]');

  const maxForms = document.querySelector('input[name="breaks-MAX_NUM_FORMS"]');

  if (!addButton || !list || !template || !totalForms) {
    return;
  }

  const configuredMax = Number.parseInt(maxForms?.value || "20", 10);

  const maximum = Math.min(
    Number.isFinite(configuredMax) ? configuredMax : 20,
    20,
  );

  const updateButton = () => {
    const total = Number.parseInt(totalForms.value, 10);

    addButton.disabled = total >= maximum;
  };

  addButton.addEventListener("click", () => {
    const current = Number.parseInt(totalForms.value, 10);

    if (!Number.isFinite(current) || current >= maximum) {
      return;
    }

    const html = template.innerHTML.replaceAll("__prefix__", String(current));

    const wrapper = document.createElement("div");
    wrapper.innerHTML = html.trim();

    const newRow = wrapper.firstElementChild;

    if (!newRow) {
      return;
    }

    const heading = newRow.querySelector("h3");

    if (heading) {
      heading.textContent = `休憩 ${current + 1}`;
    }

    list.appendChild(newRow);
    totalForms.value = String(current + 1);

    updateButton();

    const firstInput = newRow.querySelector(
      "input:not([type='hidden']):not([type='checkbox'])",
    );

    firstInput?.focus();
  });

  updateButton();
});

/* ---- static/js/step4-password.js ---- */
("use strict");

/*
 * STEP 4
 * パスワード表示・非表示
 *
 * 既存の認証処理には関与しない。
 */

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-v2-password-toggle]");

  if (!button) {
    return;
  }

  const targetId = button.getAttribute("aria-controls");

  if (!targetId) {
    return;
  }

  const field = document.getElementById(targetId);

  if (!field || !["password", "text"].includes(field.type)) {
    return;
  }

  const shouldShow = field.type === "password";

  field.type = shouldShow ? "text" : "password";

  button.setAttribute("aria-pressed", String(shouldShow));

  const label = button.querySelector("[data-v2-password-label]");

  if (label) {
    label.textContent = shouldShow ? "非表示" : "表示";
  }
});

/* ==============================================
   F11_CHARTS_V14
   E02 / A01 / A04 共通グラフ
============================================== */

(() => {
  "use strict";

  function initF11Chart(root) {
    const toggle = root.querySelector("[data-f11-toggle]");

    const table = root.querySelector("[data-f11-table]");

    const panel = root.querySelector("[data-f11-panel]");

    const canvas = root.querySelector("[data-f11-canvas]");

    const message = root.querySelector("[data-f11-message]");

    const jsonElement = root.querySelector('script[type="application/json"]');
    const linkedTable = document.getElementById(root.dataset.f11LinkedTable || "");

    if (!toggle || !table || !panel || !canvas || !message || !jsonElement) {
      return;
    }

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

    function displayTable() {
      table.hidden = Boolean(linkedTable);
      if (linkedTable) linkedTable.hidden = false;
      panel.hidden = true;

      toggle.textContent = "グラフを表示";
      toggle.setAttribute("aria-expanded", "false");
    }

    function parseData() {
      try {
        const parsed = JSON.parse(jsonElement.textContent);

        if (!parsed || !Array.isArray(parsed.rows)) {
          return null;
        }

        const valid = parsed.rows.every(
          (row) =>
            row.value === null ||
            (typeof row.value === "number" &&
              Number.isFinite(row.value) &&
              row.value >= 0),
        );

        return valid ? parsed : null;
      } catch (error) {
        return null;
      }
    }

    function reducedMotion() {
      return (
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches
      );
    }

    function createChart(data) {
      const color = "#1769c2";

      return new window.Chart(canvas, {
        type: "bar",

        data: {
          labels: data.rows.map((row) => row.label),

          datasets: [
            {
              label: data.title,

              data: data.rows.map((row) => row.value),

              backgroundColor: color,
              borderColor: "#124f91",
              borderWidth: 1,
              maxBarThickness: 26,
            },
          ],
        },

        options: {
          responsive: true,
          maintainAspectRatio: false,

          animation: reducedMotion()
            ? false
            : {
                duration: 250,
              },

          plugins: {
            legend: {
              display: false,
            },

            tooltip: {
              callbacks: {
                label(context) {
                  const row = data.rows[context.dataIndex];

                  if (!row) {
                    return "";
                  }

                  return row.display;
                },
              },
            },
          },

          scales: {
            x: {
              ticks: {
                autoSkip: true,
                maxTicksLimit: 11,
              },
            },

            y: {
              beginAtZero: true,

              title: {
                display: true,
                text: data.unit,
              },

              ticks: data.kind === "incomplete_count" ? { precision: 0 } : {},
            },
          },
        },
      });
    }

    function displayGraph() {
      clearNotice();

      if (typeof window.Chart !== "function") {
        displayTable();

        notify(
          "グラフを読み込めませんでした。" + "数値表は引き続き利用できます。",
        );

        return;
      }

      if (graphData === null) {
        graphData = parseData();
      }

      if (graphData === null) {
        displayTable();

        notify(
          "グラフ用データの読み込みに失敗しました。" +
            "数値表をご確認ください。",
        );

        return;
      }

      const hasValue = graphData.rows.some((row) => row.value !== null);

      if (!hasValue) {
        displayTable();

        notify(
          "対象期間にグラフで表示できる" +
            "完了記録がありません。" +
            "勤務状態は数値表で確認できます。",
        );

        return;
      }

      panel.hidden = false;

      try {
        if (instance === null) {
          instance = createChart(graphData);
        } else {
          instance.resize();
        }

        table.hidden = true;
        if (linkedTable) linkedTable.hidden = true;

        toggle.textContent = "表を表示";
        toggle.setAttribute("aria-expanded", "true");
      } catch (error) {
        if (instance !== null) {
          instance.destroy();
          instance = null;
        }

        displayTable();

        notify(
          "グラフの描画に失敗しました。" + "数値表は引き続き確認できます。",
        );
      }
    }

    toggle.addEventListener("click", () => {
      if (panel.hidden) {
        displayGraph();
      } else {
        clearNotice();
        displayTable();
      }
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
