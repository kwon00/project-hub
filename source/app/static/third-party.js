/* Checklist defaults and completion ratio shared by the UI and review adapter. */
(()=>{
const steps=Object.freeze(["업체 컨택하기", "설치 일자 확정", "설치 전 구성 확인(OS, 디스크, 스펙, 특이사항 등)", "솔루션 설치 파일 수신", "솔루션 적용 완료", "매뉴얼/가이드 수신", "구축 완료 보고서 수신"]);
const progress=tasks=>{const valid=(tasks||[]).filter(t=>t.text?.trim());return valid.length?Math.round(valid.filter(t=>t.done).length*100/valid.length):0;};
const sync=item=>{if(item.kind==='third_party'){item.progress=progress(item.checklist);item.status=item.progress===100?'완료':item.progress?'진행 중':'예정';}return item;};
window.ProjectHubThirdParty=Object.freeze({steps,progress,sync,newChecklist:()=>steps.map(text=>({id:crypto.randomUUID(),text,done:false}))});
})();
