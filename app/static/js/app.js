(()=>{
  const DEFAULT_DAYS=365;

  const cyElement=document.getElementById("cy");
  const detailElement=document.getElementById("detail");
  const tooltipElement=document.getElementById("tooltip");
  const daysLabelElement=document.getElementById("daysLabel");

  daysLabelElement.textContent=DEFAULT_DAYS;

  window.JobSkillGraph.init(cyElement,{
    onSkillClick:handleSkillClick,
    onJobClick:showJobDetail,
    onSkillHover:showSkillTooltip,
    onSkillHoverOut:hideSkillTooltip
  });

  document.querySelectorAll('input[name="curriculum"]').forEach(radio=>{
    radio.addEventListener("change",()=>{
      if(radio.checked){
        loadCurriculum(radio.value);
      }
    });
  });

  // 버튼 순서는 AX → DS → LLM → PA이고, 기본 화면은 세 번째 LLM.
  loadCurriculum("CUR003");

  async function loadCurriculum(curriculumCode){
    hideSkillTooltip();

    detailElement.innerHTML=`
      <div class="empty">
        Skill을 클릭하면 관련 채용공고가 표시됩니다.<br>
        채용공고 노드를 클릭하면 상세 정보를 확인할 수 있습니다.
      </div>
    `;

    try{
      const graph=await window.JobSkillApi.getGraph(curriculumCode,DEFAULT_DAYS);
      window.JobSkillGraph.render(graph.elements,curriculumCode);
    }catch(error){
      showError(error.message);
    }
  }

  async function handleSkillClick(node){
    const skillCode=node.data("skill_code");
    const skillLabel=node.data("label");

    try{
      const jobs=await window.JobSkillApi.getJobsBySkill(skillCode,DEFAULT_DAYS);

      if(jobs.length===0){
        window.JobSkillGraph.clearJobNodes();
        detailElement.innerHTML=`
          <div class="empty">
            현재 이 스킬과 연결된 채용공고가 없습니다.
          </div>
        `;
        return;
      }

      window.JobSkillGraph.addJobNodes(node,jobs);
      showJobList(skillLabel,jobs);

    }catch(error){
      showError(error.message);
    }
  }

  function showSkillTooltip(node,event){
    const jobCount=Number(node.data("job_count") || 0);

    tooltipElement.textContent=
      jobCount>0
        ? `채용공고 ${jobCount}건`
        : "현재 이 스킬과 연결된 채용공고가 없습니다.";

    tooltipElement.hidden=false;

    if(event){
      tooltipElement.style.left=`${event.clientX+12}px`;
      tooltipElement.style.top=`${event.clientY+12}px`;
    }
  }

  function hideSkillTooltip(){
    tooltipElement.hidden=true;
  }

  function normalizeTrack(track){
    return ["AX","DS","LLM","PA"].includes(track) ? track : "NONE";
  }

  function showJobList(skillLabel,jobs){
    detailElement.innerHTML=`
      <div class="job-list">
        <h2>${escapeHtml(skillLabel)} 관련 채용공고</h2>

        ${jobs.map(job=>`
          <button
            class="job-card"
            type="button"
            data-job-id="${job.job_posting_id}"
            data-track="${normalizeTrack(job.top1_track)}"
          >
            <div class="company">${escapeHtml(job.company_name)}</div>
            <div class="title">${escapeHtml(job.job_title)}</div>
          </button>
        `).join("")}
      </div>
    `;

    detailElement.querySelectorAll(".job-card").forEach(button=>{
      button.addEventListener("click",()=>{
        const job=jobs.find(
          item=>String(item.job_posting_id)===button.dataset.jobId
        );

        if(job){
          showJobDetail(job);
        }
      });
    });
  }

  function showJobDetail(job){
    const matchedSkills=(job.matched_skills || "")
      .split(",")
      .map(value=>value.trim())
      .filter(Boolean);

    const displayDate=
      job.captured_at ||
      job.published_at ||
      job.collected_at ||
      "-";

    const track=normalizeTrack(job.top1_track);

    detailElement.innerHTML=`
      <div class="job-detail" data-track="${track}">
        <h2>채용공고 상세</h2>

        <div class="label">회사명</div>
        <div class="value">${escapeHtml(job.company_name)}</div>

        <div class="label">포지션</div>
        <div class="value"><b>${escapeHtml(job.job_title)}</b></div>

        <div class="label">매칭 Skill</div>
        <div>
          ${
            matchedSkills.length
              ? matchedSkills.map(skill=>`<span class="tag">${escapeHtml(skill)}</span>`).join("")
              : "-"
          }
        </div>

        <div class="label">수집일</div>
        <div class="value">${escapeHtml(displayDate)}</div>

        ${
          job.posting_url
            ? `<a class="original-link" href="${escapeHtml(job.posting_url)}" target="_blank" rel="noopener noreferrer">원본 공고 보기</a>`
            : ""
        }
      </div>
    `;
  }

  function showError(message){
    detailElement.innerHTML=`<div class="error-box">${escapeHtml(message)}</div>`;
  }

  function escapeHtml(value){
    return String(value ?? "")
      .replaceAll("&","&amp;")
      .replaceAll("<","&lt;")
      .replaceAll(">","&gt;")
      .replaceAll('"',"&quot;")
      .replaceAll("'","&#039;");
  }
})();
