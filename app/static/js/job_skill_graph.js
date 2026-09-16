window.JobSkillGraph = {
  cy: null,

  init(container, handlers) {
    this.cy = cytoscape({
      container,
      elements: [],
      layout:{
        name:"cose",
        padding:55,
        nodeRepulsion:210000,
        idealEdgeLength:105,
        gravity:0.45
      },
      style:[
        {
          selector:"node",
          style:{
            "label":"data(label)",
            "font-size":11,
            "font-weight":650,
            "text-wrap":"wrap",
            "text-max-width":112,
            "text-valign":"center",
            "text-halign":"center",
            "background-color":"#ffffff",
            "border-width":2,
            "border-color":"#ccd6e6",
            "shape":"round-rectangle",
            "width":112,
            "height":46,
            "padding":"6px",
            "color":"#172033"
          }
        },
        {
          selector:'node[type="root"]',
          style:{
            "background-color":"#4263eb",
            "border-color":"#4263eb",
            "color":"#ffffff",
            "shape":"ellipse",
            "width":155,
            "height":60,
            "font-size":14,
            "font-weight":800
          }
        },
        {
          selector:'node[type="group"]',
          style:{
            "background-color":"#edf2ff",
            "border-color":"#748ffc",
            "color":"#364fc7",
            "width":130,
            "height":50,
            "font-size":12,
            "font-weight":800
          }
        },
        {
          selector:'node[type="skill"][job_count = 0]',
          style:{
            "background-color":"#eceff3",
            "border-color":"#d8dde5",
            "color":"#9aa3b2"
          }
        },
        {
          selector:'node[type="job"]',
          style:{
            "background-color":"#fff4e6",
            "border-color":"#f59f00",
            "color":"#7c4a03",
            "width":150,
            "height":56,
            "font-size":10,
            "text-max-width":136,
            "padding":"7px"
          }
        },
        {
          selector:"edge",
          style:{
            "line-color":"#d7deea",
            "target-arrow-color":"#d7deea",
            "target-arrow-shape":"triangle",
            "curve-style":"bezier",
            "width":1.15,
            "opacity":0.82
          }
        },
        {
          selector:'edge[type="curriculum_group"]',
          style:{
            "line-color":"#aebddd",
            "target-arrow-color":"#aebddd",
            "width":1.7,
            "opacity":0.95
          }
        },
        {
          selector:'edge[type="job"]',
          style:{
            "line-color":"#f6b94a",
            "target-arrow-color":"#f6b94a",
            "width":2,
            "opacity":1
          }
        }
      ]
    });

    this.cy.on("tap","node",event=>{
      const node=event.target;
      const type=node.data("type");

      if(type==="skill"){
        const jobCount=Number(node.data("job_count") || 0);
        if(jobCount===0) return;
        handlers.onSkillClick(node);
        return;
      }

      if(type==="job"){
        handlers.onJobClick(node.data());
      }
    });

    this.cy.on("mouseover",'node[type="skill"]',event=>{
      handlers.onSkillHover(event.target,event.originalEvent);
    });

    this.cy.on("mousemove",'node[type="skill"]',event=>{
      handlers.onSkillHover(event.target,event.originalEvent);
    });

    this.cy.on("mouseout",'node[type="skill"]',()=>{
      handlers.onSkillHoverOut();
    });
  },

  render(elements){
    this.cy.elements().remove();
    this.cy.add(elements);

    this.cy.layout({
      name:"cose",
      animate:false,
      padding:55,
      nodeRepulsion:210000,
      idealEdgeLength:105,
      gravity:0.45
    }).run();

    this.cy.fit(undefined,45);
  },

  clearJobNodes(){
    this.cy.edges('[type="job"]').remove();
    this.cy.nodes('[type="job"]').remove();
  },

  addJobNodes(skillNode,jobs){
    this.clearJobNodes();
    const elements=[];

    jobs.forEach(job=>{
      const jobNodeId=`job_${job.job_posting_id}`;

      elements.push({
        data:{
          id:jobNodeId,
          label:`${job.company_name}\n${job.job_title}`,
          type:"job",
          ...job
        }
      });

      elements.push({
        data:{
          id:`edge_${skillNode.id()}_${jobNodeId}`,
          source:skillNode.id(),
          target:jobNodeId,
          type:"job"
        }
      });
    });

    this.cy.add(elements);

    this.cy.layout({
      name:"cose",
      animate:true,
      padding:55,
      nodeRepulsion:210000,
      idealEdgeLength:105,
      gravity:0.45
    }).run();
  }
};
