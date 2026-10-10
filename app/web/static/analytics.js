/* AMP XP v1.20.3.1 — analytics chart rendering from inert JSON template data. */
(function () {
  'use strict';
  const source=document.getElementById('analytics-metrics-data');
  if(!source||typeof Chart==='undefined')return;
  let metrics={};try{metrics=JSON.parse(source.content?source.content.textContent:source.textContent||'{}');}catch(_err){return;}
  const chartBase='#06AEBB';
  const palette=['#06AEBB','#6C63FF','#2FAE75','#F3A63A','#E86C8D','#5C86D9','#8C6CCF','#42A5A5','#D47B45','#6D8C75','#A0A7B4'];
  function createChart(metric){if(metric.kind==='heatmap')return;const el=document.getElementById(`chart-${metric.key}`);if(!el)return;const doughnut=metric.kind==='doughnut';new Chart(el,{type:metric.kind,data:{labels:metric.labels,datasets:[{label:metric.value_label,data:metric.values,borderWidth:2,tension:.28,fill:false,borderColor:doughnut?palette:chartBase,backgroundColor:doughnut?palette:'rgba(6,174,187,.22)',pointBackgroundColor:chartBase}]},options:{responsive:true,maintainAspectRatio:false,indexAxis:(metric.kind==='bar'&&(metric.labels.length>7||metric.labels.some(value=>String(value).length>20)))?'y':'x',plugins:{legend:{display:doughnut,position:'bottom'},tooltip:{displayColors:false}},scales:doughnut?{}:{x:{grid:{display:false},ticks:{autoSkip:false,maxRotation:35,minRotation:0}},y:{beginAtZero:true,ticks:{precision:0}}}}});}
  Object.values(metrics).forEach(createChart);
  document.querySelectorAll('.analytics-chart-clickable').forEach(wrap=>{wrap.setAttribute('role','link');wrap.setAttribute('tabindex','0');const open=()=>{if(wrap.dataset.detailUrl)location.href=wrap.dataset.detailUrl;};wrap.addEventListener('click',open);wrap.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}});});
})();
