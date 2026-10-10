/* AMP XP v1.20.2 — analytics detail chart and drill-down. */
(function () {
  'use strict';
  const source=document.getElementById('analytics-metric-data');if(!source)return;
  let metric;try{metric=JSON.parse(source.content?source.content.textContent:source.textContent||'{}');}catch(_err){return;}
  function setDrill(label,value,secondary){const target=document.getElementById('drillLabel');if(!target)return;target.textContent=label??'—';const valueEl=document.getElementById('drillValue'),secondaryEl=document.getElementById('drillSecondary');if(valueEl)valueEl.textContent=value??'—';if(secondaryEl)secondaryEl.textContent=secondary||'—';}
  function showDrill(index){const row=(metric.rows||[])[index];if(row)setDrill(row.label,row.display_value!==undefined?row.display_value:row.value,row.secondary);}
  if(metric.kind!=='heatmap'&&typeof Chart!=='undefined'){
    const canvas=document.getElementById('detailChart');if(canvas){const palette=['#06AEBB','#6C63FF','#2FAE75','#F3A63A','#E86C8D','#5C86D9','#8C6CCF','#42A5A5','#D47B45','#6D8C75','#A0A7B4'];const doughnut=metric.kind==='doughnut';new Chart(canvas,{type:metric.kind,data:{labels:metric.labels,datasets:[{label:metric.value_label,data:metric.values,borderWidth:2,tension:.28,fill:false,borderColor:doughnut?palette:'#06AEBB',backgroundColor:doughnut?palette:'rgba(6,174,187,.22)',pointBackgroundColor:'#06AEBB'}]},options:{responsive:true,maintainAspectRatio:false,indexAxis:(metric.kind==='bar'&&(metric.labels.length>7||metric.labels.some(value=>String(value).length>20)))?'y':'x',plugins:{legend:{display:doughnut,position:'bottom'},tooltip:{displayColors:false}},scales:doughnut?{}:{x:{grid:{display:false},ticks:{autoSkip:false,maxRotation:35,minRotation:0}},y:{beginAtZero:true,ticks:{precision:0}}},onClick:(_event,elements)=>{if(elements.length)showDrill(elements[0].index);}}});}}
  document.querySelectorAll('.analytics-drill-row').forEach(row=>{const show=()=>setDrill(row.dataset.label,row.dataset.value,row.dataset.secondary);row.addEventListener('click',show);row.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();show();}});});
})();
