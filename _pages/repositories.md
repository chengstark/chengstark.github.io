---
layout: page
permalink: /repositories/
title: repositories
description: Selected open-source research software and code.
nav: true
nav_order: 4
---

Research code accompanying my work. You can also browse [all of my repositories](https://github.com/{{ site.github_username }}).

{% if site.data.repositories.github_repos %}

## Selected repositories

<div class="repositories d-flex flex-wrap">
  {% for repo in site.data.repositories.github_repos %}
    {% include repository/repo.liquid repository=repo %}
  {% endfor %}
</div>
{% endif %}
