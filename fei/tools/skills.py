from fei.tools.base import Tool
from fei.skills import list_skills, load_skill

list_tool = Tool("list_skills", "Discover project-local instruction skills in .fei/skills/<name>/SKILL.md; returns name and preview. Skills are instructions, not executable plugins.", {"type":"object", "properties":{}, "additionalProperties":False}, list_skills)
load_tool = Tool("load_skill", "Load a named project skill on demand. Instructions are preserved separately through compression; user instructions and tool permissions take precedence. Only load relevant skills. At most four skills / 24 KiB combined.", {"type":"object", "properties":{"name":{"type":"string", "minLength":1, "maxLength":64}}, "required":["name"], "additionalProperties":False}, load_skill)
