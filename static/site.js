(function () {
  document.querySelectorAll(".stage-tabs button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.getAttribute("data-stage");
      document.querySelectorAll(".stage-tabs button").forEach(function (b) {
        b.classList.toggle("is-on", b === btn);
        b.setAttribute("aria-selected", b === btn ? "true" : "false");
      });
      document.querySelectorAll(".stage").forEach(function (panel) {
        panel.classList.toggle("is-on", panel.id === "stage-" + id);
      });
    });
  });
})();
