# Roadmap

## [ ] - make next-requirements command interactive

The next-requirements command should aid in establishing the list of requirements for a feature/task. When given arguments it should take that as the users starting point, and help from there until the user is satisfied with the list of requirements.
When the user is satsified, the frontmatter of the requirements.md file should be updated to have `status: approved`, otherwise it should have `status: draft`.

## [x] - Enrich trusted_dirs

Enrich trusted_dirs to be a dict ("name", "desc", "location") with desc describing what the folder is used for (may be empty). (Update the local config.yml to have a folder named "development", with desc "dev projects" to make the dev folder point to "/Users/Morriz/Documents/Workspace/morriz").
Make teleclaude/config.py's ComputerConfig return the list with the `default_working_dir` merged with desc "TeleClaude folder".

Also add a `host` field that can be empty or a hostname/ip. If set, teleclaude can ssh into that host and run commands there (assuming the trusted_dir is mounted there too). Add proper descriptions to all fields so AI understands them.

## [ ] - New dev project from skaffolding

Create feature to be able to start a whole new project next to TeleClaude project folder based on other project's skaffolding.

We have many projects in different folders on the computer and we would like to point to one of those and create a new project folder based on that example project. It should then create a new project folder (in the trusted_dir desginated as development folder) and only migrate the necessary, tooling and scaffolding files to that new `{developmentFolder}/{newProjectName}` location. This process should be interactive with the user so that any questions are answered before you do things that affects the architecture. Do NOT copy over source files from the example project, only the scaffolding and tooling files. It should be clear to the AI what to do next.
