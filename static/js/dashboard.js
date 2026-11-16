(function () {
  const canvas = document.getElementById("sales-chart");
  const dataEl = document.getElementById("chart-data");
  if (!canvas || !dataEl) return;
  if (typeof Chart === "undefined") { const f = document.getElementById("chart-fallback"); if (f) f.hidden = false; return; }
  const d = JSON.parse(dataEl.textContent);
  new Chart(canvas, {
    type: "line",
    data: {
      labels: d.labels,
      datasets: [
        { label: "Net sales", data: d.revenue, borderColor: "#0b965b", backgroundColor: "rgba(11,150,91,.13)",
          borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 5, pointBackgroundColor: "#0b965b", tension: 0.38, fill: true },
        { label: "Gross profit", data: d.gross, borderColor: "#e4a633", backgroundColor: "rgba(228,166,51,.08)",
          borderWidth: 2, pointRadius: 2, pointHoverRadius: 4, pointBackgroundColor: "#e4a633", tension: 0.38, fill: false },
      ],
    },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      scales: { x: { grid: { display: false }, ticks: { color: "#70877d", maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
        y: { beginAtZero: true, grid: { color: "rgba(33,87,62,.08)" }, ticks: { color: "#70877d", callback: function (v) { return Number(v).toLocaleString(); } } } },
      plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 7, color: "#59766a", font: { size: 11 } } },
        tooltip: { callbacks: { label: function (context) { return context.dataset.label + ": " + (d.currency || "Rs.") + " " + Number(context.parsed.y).toLocaleString(); } } } } },
  });
})();
