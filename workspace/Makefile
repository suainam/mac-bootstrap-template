SHELL := /usr/bin/env bash

SCRIPTS_DIR := $(HOME)/work/scripts

.PHONY: help new-project new-analysis-subproject list-projects organize-downloads cache-report \
	clean-cache clean-cache-aggressive doctor projects-guide

help:
	@printf '%s\n' \
	  'Available targets:' \
	  '  make new-project              Create a new repo under ~/work/projects' \
	  '  make new-analysis-subproject  Create a subproject inside an analysis repo' \
	  '  make list-projects            List repos under ~/work/projects' \
	  '  make organize-downloads       Sort files from ~/Downloads' \
	  '  make cache-report             Show largest cache directories' \
	  '  make clean-cache              Run safe cache cleanup' \
	  '  make doctor                   Run machine health checks' \
	  '  make projects-guide          Show the local guide path'

new-project:
	"$(SCRIPTS_DIR)/new-project" "$(NAME)" "$(DESC)"

new-analysis-subproject:
	"$(SCRIPTS_DIR)/new-analysis-subproject" "$(PROJECT_ROOT)" "$(CONTAINER)" "$(NAME)"

list-projects:
	"$(SCRIPTS_DIR)/list-projects"

organize-downloads:
	"$(SCRIPTS_DIR)/organize-downloads"

cache-report:
	"$(SCRIPTS_DIR)/cache-report"

clean-cache:
	"$(SCRIPTS_DIR)/clean-cache"

clean-cache-aggressive:
	"$(SCRIPTS_DIR)/clean-cache" --aggressive

doctor:
	"$(SCRIPTS_DIR)/doctor"

projects-guide:
	@printf '%s\n' '$(HOME)/work/PROJECTS_GUIDE.md'
