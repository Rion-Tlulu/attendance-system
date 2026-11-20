document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("form[data-number-candidate-url]");
  const select = form?.querySelector("[name=department_choice]");
  const output = document.getElementById("employee-number-candidate");
  const candidate = form?.querySelector("[name=displayed_candidate]");
  if (!form || !select || !output) return;

  let currentRequest;
  const update = async () => {
    currentRequest?.abort();
    if (candidate) candidate.value = "";
    if (!select.value) {
      output.classList.add("is-message");
      output.textContent = "部署を選択すると候補を表示します。";
      return;
    }
    const controller = new AbortController();
    currentRequest = controller;
    output.classList.add("is-message");
    output.textContent = "候補を取得中です。";
    const url = new URL(form.dataset.numberCandidateUrl, window.location.href);
    url.searchParams.set("department", select.value);
    if (form.dataset.employeeId) url.searchParams.set("employee", form.dataset.employeeId);
    try {
      const response = await fetch(url, { credentials: "same-origin", signal: controller.signal });
      const result = await response.json();
      if (controller !== currentRequest) return;
      if (response.ok && candidate) candidate.value = result.number;
      output.classList.toggle("is-message", !response.ok);
      output.textContent = response.ok
        ? result.number
        : `${result.error || "候補を取得できませんでした。"} 再度部署を選択してください。`;
    } catch (error) {
      if (error.name !== "AbortError" && controller === currentRequest) {
        output.classList.add("is-message");
        output.textContent = "候補を取得できませんでした。再度部署を選択してください。";
      }
    }
  };
  select.addEventListener("change", update);
  if (select.value) update();
});
