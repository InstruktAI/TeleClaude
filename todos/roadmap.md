# Roadmap

## [ ] - make next-requirements command interactive

The requirements command should not assume requirements that have unclear input, but must always seek clarification from user first. DON'T bother the user for things you CAN safely assume, or are not impactful from an architectural/UX perspective.

When the user calls `/next-requirements` the bot should present the current list of requirements and ask if the user wants to make any changes. If the user wants to make changes, the bot should guide the user through the process of adding, removing or modifying requirements.

## [ ] - Enrich trusted_dirs

Enrich trusted_dirs to be a dict ("name", "desc", "location") with desc describing what the folder is used for (may be empty). (Update the local config.yml to have a folder named "development", with desc "dev projects" to make the dev folder point to "/Users/Morriz/Documents/Workspace/morriz").

## [ ] - New dev project from skaffolding

Create feature to be able to start a whole new project next to TeleClaude project folder based on other project's skaffolding.

We have many projects in different folders on the computer and we would like to point to one of those and create a new project folder based on that example project. It should then create a new project folder (in the trusted_dir desginated as development folder) and only migrate the necessary, tooling and scaffolding files to that new `{developmentFolder}/{newProjectName}` location. This process should be interactive with the user so that any questions are answered before you do things that affects the architecture. Do NOT copy over source files from the example project, only the scaffolding and tooling files. It should be clear to the AI what to do next.
