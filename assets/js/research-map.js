(() => {
  const stage = document.querySelector(".research-map__stage");
  const dataElement = document.getElementById("research-map-data");

  if (!stage || !dataElement || typeof window.d3 === "undefined") return;

  const d3 = window.d3;
  const data = JSON.parse(dataElement.textContent);
  const baseUrl = stage.dataset.baseurl || "";
  const svg = d3.select(stage.querySelector(".research-map__canvas"));
  const tooltip = stage.querySelector(".research-map__tooltip");
  const filters = document.querySelectorAll(".research-map__filter");
  const controls = document.querySelectorAll(".research-map__control");
  const details = {
    image: document.querySelector(".research-map__details-image"),
    topic: document.querySelector(".research-map__details-topic"),
    title: document.querySelector(".research-map__details-title"),
    meta: document.querySelector(".research-map__details-meta"),
    summary: document.querySelector(".research-map__details-summary"),
    related: document.querySelector(".research-map__details-related"),
    link: document.querySelector(".research-map__paper-link"),
    progress: document.querySelector(".research-map__in-progress"),
  };
  const clusterById = new Map(data.clusters.map((cluster) => [cluster.id, cluster]));
  const nodeById = new Map(data.nodes.map((node) => [node.id, node]));
  const adjacency = new Map(data.nodes.map((node) => [node.id, new Set()]));

  data.links.forEach((link) => {
    const sourceNeighbors = adjacency.get(link.source);
    const targetNeighbors = adjacency.get(link.target);
    if (sourceNeighbors) sourceNeighbors.add(link.target);
    if (targetNeighbors) targetNeighbors.add(link.source);
  });

  let selectedCluster = "all";
  let selectedNodeId = null;
  let simulation;
  let zoomBehavior;
  let rootLayer;
  let linkSelection;
  let nodeSelection;
  let clusterSelection;
  let resizeTimer;

  const imageUrl = (path) => `${baseUrl}/${path}`.replace(/\/+/g, "/");
  const endpointId = (endpoint) => (typeof endpoint === "object" ? endpoint.id : endpoint);

  function clusterLayout(width, height) {
    if (width < 640) {
      const clusterGap = (height - 250) / Math.max(data.clusters.length - 1, 1);
      return new Map(data.clusters.map((cluster, index) => [cluster.id, { x: width / 2, y: 125 + index * clusterGap }]));
    }

    return new Map([
      ["wearable-physiological-signals", { x: width * 0.19, y: height * 0.52 }],
      ["scientific-discovery", { x: width * 0.5, y: height * 0.48 }],
      ["clinical-ai", { x: width * 0.81, y: height * 0.52 }],
      ["interpretable-ai", { x: width * 0.5, y: height * 0.82 }],
    ]);
  }

  function updateEmphasis() {
    const neighbors = selectedNodeId ? adjacency.get(selectedNodeId) : null;

    nodeSelection
      .classed("is-selected", (node) => node.id === selectedNodeId)
      .attr("opacity", (node) => {
        if (selectedNodeId) return node.id === selectedNodeId || (neighbors && neighbors.has(node.id)) ? 1 : 0.16;
        if (selectedCluster !== "all") return node.cluster === selectedCluster ? 1 : 0.16;
        return 1;
      });

    linkSelection.attr("opacity", (link) => {
      const source = endpointId(link.source);
      const target = endpointId(link.target);

      if (selectedNodeId) return source === selectedNodeId || target === selectedNodeId ? 1 : 0.08;
      if (selectedCluster !== "all") {
        return nodeById.get(source).cluster === selectedCluster && nodeById.get(target).cluster === selectedCluster ? 0.9 : 0.08;
      }
      return 1;
    });

    clusterSelection.attr("opacity", (cluster) => (selectedCluster === "all" || cluster.id === selectedCluster ? 1 : 0.25));
  }

  function showDetails(node) {
    const cluster = clusterById.get(node.cluster);
    const related = Array.from(adjacency.get(node.id) || [])
      .map((id) => nodeById.get(id).label)
      .filter(Boolean);

    details.image.src = imageUrl(node.preview);
    details.image.alt = `Preview for ${node.title}`;
    details.image.hidden = false;
    details.topic.textContent = cluster.label;
    details.topic.style.color = cluster.color;
    details.title.textContent = node.title;
    details.meta.textContent = `${node.venue} · ${node.year}${node.featured ? " · Selected publication" : ""}`;
    details.summary.textContent = node.summary;
    details.related.textContent = related.length ? `Connected to: ${related.join(", ")}.` : "";
    details.related.hidden = !related.length;
    details.link.hidden = !node.url;
    details.progress.hidden = Boolean(node.url);

    if (node.url) details.link.href = node.url;
  }

  function selectNode(node) {
    selectedNodeId = selectedNodeId === node.id ? null : node.id;

    if (selectedNodeId) {
      showDetails(node);
    } else {
      details.topic.textContent = "Explore the map";
      details.topic.style.color = "";
      details.title.textContent = "Select a paper";
      details.meta.textContent = "Drag nodes to rearrange them, or pan and zoom the canvas.";
      details.summary.textContent = "Connections represent shared methods, research questions, or application areas.";
      details.related.hidden = true;
      details.image.hidden = true;
      details.link.hidden = true;
      details.progress.hidden = true;
    }

    updateEmphasis();
  }

  function render() {
    const width = Math.max(stage.clientWidth, 320);
    const height = width < 640 ? 900 : Math.max(600, Math.min(720, width * 0.72));
    const centers = clusterLayout(width, height);

    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("height", height);

    rootLayer = svg.append("g");
    const defs = rootLayer.append("defs");

    data.nodes.forEach((node) => {
      const radius = node.featured ? 34 : 28;
      const pattern = defs
        .append("pattern")
        .attr("id", `research-map-image-${node.id}`)
        .attr("width", 1)
        .attr("height", 1)
        .attr("patternContentUnits", "objectBoundingBox");

      pattern.append("image").attr("href", imageUrl(node.preview)).attr("width", 1).attr("height", 1).attr("preserveAspectRatio", "xMidYMid slice");

      node.radius = radius;
    });

    clusterSelection = rootLayer
      .append("g")
      .selectAll("text")
      .data(data.clusters)
      .join("text")
      .attr("class", "research-map__cluster-label")
      .attr("x", (cluster) => centers.get(cluster.id).x)
      .attr("y", (cluster) => centers.get(cluster.id).y - (width < 640 ? 100 : cluster.id === "interpretable-ai" ? 110 : 170))
      .text((cluster) => cluster.label);

    linkSelection = rootLayer
      .append("g")
      .attr("aria-hidden", "true")
      .selectAll("line")
      .data(data.links)
      .join("line")
      .attr("class", "research-map__link");

    nodeSelection = rootLayer
      .append("g")
      .selectAll("g")
      .data(data.nodes, (node) => node.id)
      .join("g")
      .attr("class", "research-map__node")
      .attr("role", "button")
      .attr("tabindex", 0)
      .attr("aria-label", (node) => `${node.title}, ${node.venue}, ${node.year}`)
      .on("click", (event, node) => {
        event.stopPropagation();
        selectNode(node);
      })
      .on("keydown", (event, node) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectNode(node);
        }
      })
      .on("mouseenter", (event, node) => {
        tooltip.textContent = `${node.title} (${node.year})`;
        tooltip.classList.add("is-visible");
      })
      .on("mousemove", (event) => {
        const bounds = stage.getBoundingClientRect();
        tooltip.style.left = `${event.clientX - bounds.left}px`;
        tooltip.style.top = `${event.clientY - bounds.top}px`;
      })
      .on("mouseleave", () => tooltip.classList.remove("is-visible"));

    nodeSelection
      .append("circle")
      .attr("r", (node) => node.radius)
      .attr("fill", (node) => `url(#research-map-image-${node.id})`)
      .attr("stroke", (node) => clusterById.get(node.cluster).color);

    nodeSelection
      .filter((node) => node.featured)
      .append("circle")
      .attr("class", "research-map__featured-ring")
      .attr("r", (node) => node.radius - 5);

    nodeSelection
      .append("text")
      .attr("class", "research-map__node-label")
      .attr("y", (node) => node.radius + 16)
      .text((node) => node.label);

    const drag = d3
      .drag()
      .on("start", (event, node) => {
        if (!event.active) simulation.alphaTarget(0.2).restart();
        node.fx = node.x;
        node.fy = node.y;
      })
      .on("drag", (event, node) => {
        node.fx = event.x;
        node.fy = event.y;
      })
      .on("end", (event, node) => {
        if (!event.active) simulation.alphaTarget(0);
        node.fx = null;
        node.fy = null;
      });

    nodeSelection.call(drag);

    if (simulation) simulation.stop();
    simulation = d3
      .forceSimulation(data.nodes)
      .force(
        "link",
        d3
          .forceLink(data.links)
          .id((node) => node.id)
          .distance((link) => (nodeById.get(endpointId(link.source)).cluster === nodeById.get(endpointId(link.target)).cluster ? 88 : 145))
          .strength(0.12)
      )
      .force("charge", d3.forceManyBody().strength(-125))
      .force(
        "collide",
        d3
          .forceCollide()
          .radius((node) => node.radius + 21)
          .iterations(2)
      )
      .force("x", d3.forceX((node) => centers.get(node.cluster).x).strength(0.19))
      .force("y", d3.forceY((node) => centers.get(node.cluster).y).strength(0.19))
      .on("tick", () => {
        linkSelection
          .attr("x1", (link) => link.source.x)
          .attr("y1", (link) => link.source.y)
          .attr("x2", (link) => link.target.x)
          .attr("y2", (link) => link.target.y);

        nodeSelection.attr("transform", (node) => {
          const padding = node.radius + 8;
          node.x = Math.max(padding, Math.min(width - padding, node.x));
          node.y = Math.max(padding, Math.min(height - padding - 18, node.y));
          return `translate(${node.x},${node.y})`;
        });
      });

    zoomBehavior = d3
      .zoom()
      .scaleExtent([0.65, 2.3])
      .filter((event) => !(event.target.closest && event.target.closest(".research-map__node")))
      .on("zoom", (event) => rootLayer.attr("transform", event.transform));

    svg
      .call(zoomBehavior)
      .on("dblclick.zoom", null)
      .on("click", () => {
        if (selectedNodeId) selectNode(nodeById.get(selectedNodeId));
      });

    updateEmphasis();
  }

  filters.forEach((filter) => {
    filter.addEventListener("click", () => {
      if (selectedNodeId) selectNode(nodeById.get(selectedNodeId));
      selectedCluster = filter.dataset.cluster;
      filters.forEach((button) => {
        const active = button === filter;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      updateEmphasis();
    });
  });

  controls.forEach((control) => {
    control.addEventListener("click", () => {
      const action = control.dataset.mapAction;
      if (action === "zoom-in") svg.transition().duration(180).call(zoomBehavior.scaleBy, 1.25);
      if (action === "zoom-out") svg.transition().duration(180).call(zoomBehavior.scaleBy, 0.8);
      if (action === "reset") svg.transition().duration(220).call(zoomBehavior.transform, d3.zoomIdentity);
    });
  });

  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(render, 180);
  });

  render();
})();
