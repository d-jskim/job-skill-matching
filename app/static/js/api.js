window.JobSkillApi = {
  async getGraph(curriculumCode, days) {
    const url = `/api/graph?curriculum_code=${encodeURIComponent(curriculumCode)}&days=${days}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error("그래프 데이터를 불러오지 못했습니다.");
    return response.json();
  },

  async getJobsBySkill(skillCode, days) {
    const url = `/api/jobs/by-skill/${encodeURIComponent(skillCode)}?days=${days}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error("채용공고를 불러오지 못했습니다.");
    return response.json();
  }
};
