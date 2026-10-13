# Changelog

All notable changes to TeleClaude are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.9.0] - 2026-10-13

> VoxCPM supports per-voice synthesis parameters and refreshes cached Discord audio when effective parameters change. Documentation convergence now serializes repository operations, distinguishes held work from failures, and improves rollback after partial operations. Upgrade scripts should recognize convergence status 3; actual convergence failures now fail installation. Full-root platform-home sync can recover missing legacy publication history. Daemon teardown continues after ordinary cleanup faults, and Redis intake handles a broader range of request failures.


- [b2ea6e8](https://github.com/InstruktAI/TeleClaude/commit/b2ea6e800ddf7342754709343c0eea500c77322a) chore(docs): reconcile lifecycle markers for missing-publisher-owner-surfacing
- [47315e0](https://github.com/InstruktAI/TeleClaude/commit/47315e01370eb8b34fb10dffbd25a09970198432) fix(convergence): serialize layout migration and report real install failures
- [f91ce5e](https://github.com/InstruktAI/TeleClaude/commit/f91ce5e4e609e74669fa633924337cf8dad8dc5c) chore(docs): reconcile lifecycle markers for convergence-overlap-and-failure-reporting
- [fffb990](https://github.com/InstruktAI/TeleClaude/commit/fffb99065e4490a809ed1b6bca85c9ffe2f0049d) fix(relay): contain message failures without terminating intake
- [32ae917](https://github.com/InstruktAI/TeleClaude/commit/32ae917da38c6f83274003dbf9a5bb7a3c85b587) chore(docs): reconcile lifecycle markers for relay-intake-dies-on-unhandled-refusal
- [61a16c5](https://github.com/InstruktAI/TeleClaude/commit/61a16c5220b89a3f7f9fd8814f871e69bf3d2166) fix(tts): preserve and apply VoxCPM voice parameter overrides
- [6001bb6](https://github.com/InstruktAI/TeleClaude/commit/6001bb6521795636d937abfa1138bd28f3a120bf) chore: reconcile release metadata for v0.8.0 [skip ci]
- [dd51c73](https://github.com/InstruktAI/TeleClaude/commit/dd51c736577da6d7f57c76ce7f422448f026769e) docs(sdlc): scope a bug fix to every site of its diagnosed mechanism
- [6a4f78f](https://github.com/InstruktAI/TeleClaude/commit/6a4f78f4f03d99886c7e979f5f2a5624f3e596ad) docs(config): expose the VoxCPM voice override contract
- [66bb909](https://github.com/InstruktAI/TeleClaude/commit/66bb909acaa8664f9d0bb7df35b72f07ef947fdc) docs(sdlc): bind family-site obligations to confirmed matches and admitted evidence
- [0538030](https://github.com/InstruktAI/TeleClaude/commit/0538030d9b93afc946c5544301bd465741addbd8) fix(runtime): isolate post-settlement teardown failures
- [a753c2f](https://github.com/InstruktAI/TeleClaude/commit/a753c2fc4e2d6c5f4ad58e5c5c590571350fe6fe) fix(runtime): align shutdown cleanup diagnostics
- [6e12d9c](https://github.com/InstruktAI/TeleClaude/commit/6e12d9c13d2fccd6f931b2536d3953a13aa96936) fix(context): rebuild homes with unavailable legacy history
- [d527def](https://github.com/InstruktAI/TeleClaude/commit/d527def32ab3bc92201a4cf74166d8e60ca8083d) fix(context): require native full-length publication IDs
- [9d62db3](https://github.com/InstruktAI/TeleClaude/commit/9d62db3299076bc0f39e2e8dd88649b59860384e) fix(context): own Git storage format vocabulary
- [9b3ace9](https://github.com/InstruktAI/TeleClaude/commit/9b3ace98c71415b35d4c5b7335a9b726caac693b) docs(delivery): separate release operation from contributor development [skip ci]

**Full diff:** [v0.8.0...v0.9.0](https://github.com/InstruktAI/TeleClaude/compare/v0.8.0...v0.9.0)

## [0.8.0] - 2026-10-13

> Target computer-owned workflows with --computer/-c, issue invitations through the mesh master, and curate conversation memories through identity-addressed extractions. New extraction-request and mirror-coverage events coordinate memory processing. Session pruning retains records, and history tracks conversation lineage and coverage.
> 
> Upgrade implications: update participating peers for the new relay protocol and verify destination-side identity registrations. Replace automation using send_telegram.py; migration 22 removes its alert fields. Review strict boolean values, nested enabled settings, and master-only Telegram/WhatsApp/email placement. Startup retires legacy memory workers and migrates read progress into extraction storage; conversation memory context excludes unscoped legacy observations. Database and mirror-store migrations change persisted structures, so rollback requires compatible stored state. Package installation now requires Python >=3.12,<3.15. TeleClaude's own commit boundary additionally requires cold runtime acceptance to pass.


- [1ed2cd9](https://github.com/InstruktAI/TeleClaude/commit/1ed2cd9426070dd193c6bcee495a8cf466c9c175) chore: diagnose on med [skip ci]
- [f489f19](https://github.com/InstruktAI/TeleClaude/commit/f489f1998758fc991713ad6b3a6ef7d375fc1e6f) docs(release): define repeatable manual versions and complete commit notes [skip ci]
- [6143316](https://github.com/InstruktAI/TeleClaude/commit/6143316c7ca0583db5f2712b8cc4ad9a0d6d5209) docs(quality): permit bounded CLI acceptance journeys; align pending release gates [skip ci]
- [e80e132](https://github.com/InstruktAI/TeleClaude/commit/e80e1322a628366fb53306127fc480bed3ec1a10) docs(quality): bind refusal journeys to public contracts [skip ci]
- [7a81bed](https://github.com/InstruktAI/TeleClaude/commit/7a81bed5cf889d37a545a2e268685a88df4695c5) docs(ci): ground hosted runtime and isolated dependency environments [skip ci]
- [ab4fb06](https://github.com/InstruktAI/TeleClaude/commit/ab4fb062f9ad3da90c46fba5248cf29f1bece46c) docs(release): bind runtime acceptance to recoverable proof [skip ci]
- [ae207a9](https://github.com/InstruktAI/TeleClaude/commit/ae207a9592b7b34d10429ab69bbc6a4747d904d4) docs(ci): separate upstream facts from harness design [skip ci]
- [912fbc3](https://github.com/InstruktAI/TeleClaude/commit/912fbc3049e31dbf888724aeaca31ecfd68fe5fb) perf(quality): overlap independent checks and reuse Markdown parsing
- [1abcff4](https://github.com/InstruktAI/TeleClaude/commit/1abcff4983c83ef37fcdc85a6f92631ba79a891b) docs(release): align manual flow with prerequisite runtime proof [skip ci]
- [58d7e59](https://github.com/InstruktAI/TeleClaude/commit/58d7e59b7ee7dec4a76d39de03d30265cbca21db) docs(quality): align shared lint sequencing with concurrent checks
- [e847e83](https://github.com/InstruktAI/TeleClaude/commit/e847e83989be69e141fb95644fb5b63dc420f1ba) chore(deps): update dependency setuptools to v83 [security] (#114)
- [3d2348a](https://github.com/InstruktAI/TeleClaude/commit/3d2348a6deb4ade5d0e3ac36d003003f1ae23bfb) fix(deps): update dependency discord-api-types to v0.38.56 (#115)
- [324c1f2](https://github.com/InstruktAI/TeleClaude/commit/324c1f282dc0d44c620c2afac61c18a3c2cbbd55) chore(deps): update dependency simple-icons to v16.35.0 (#118)
- [043bee0](https://github.com/InstruktAI/TeleClaude/commit/043bee0f2b6555a2682b538f1a03d1c594b14a73) chore(deps): update dependency parse5 to v8 (#116)
- [9402767](https://github.com/InstruktAI/TeleClaude/commit/940276782916565d98406b6673f7b63483f2becc) feat(quality): gate delivery on isolated CLI runtime acceptance
- [81accc2](https://github.com/InstruktAI/TeleClaude/commit/81accc21b2f55e332aeff65abc0135b98a8dcdce) chore(docs): reconcile lifecycle markers for cli-runtime-smoke-harness
- [580ef1f](https://github.com/InstruktAI/TeleClaude/commit/580ef1f2f4d3edbb7393c088976acdbf666fc5b9) fix(ci): read installed computer identity in runtime acceptance
- [e5d259a](https://github.com/InstruktAI/TeleClaude/commit/e5d259a6faedb2c5f2da2e8e3ece13df8ab453ab) fix(ci): retain CLI evidence for failed acceptance assertions
- [d7bc321](https://github.com/InstruktAI/TeleClaude/commit/d7bc321b9a861160e040525183b9f50da5c19d86) fix(ci): scope acceptance diagnostics to the failed command
- [eec58ac](https://github.com/InstruktAI/TeleClaude/commit/eec58ac304ad86a5336f73ec2004d596745c66dc) docs(agent-runtime): define caller-owned silence assessment
- [1b75fd9](https://github.com/InstruktAI/TeleClaude/commit/1b75fd9aff0d3c14913eb3853f86118d463215fa) fix(ci): bind readiness to the public daemon status contract
- [29cf2ee](https://github.com/InstruktAI/TeleClaude/commit/29cf2eed998b2b085f26f8ac2778e08c4ad8b4ae) docs(agent-runtime): state the bounded observation delivery gap
- [dd82393](https://github.com/InstruktAI/TeleClaude/commit/dd82393879a700bfd2a33a8bc26ea25a16258e1f) fix(ci): snapshot the public local readiness response
- [16284fc](https://github.com/InstruktAI/TeleClaude/commit/16284fce928d02b2aa5e62370a3ac21724dfce37) fix(ci): await config restart before subsequent runtime journeys
- [5d012c9](https://github.com/InstruktAI/TeleClaude/commit/5d012c92d9e3d8ba78d3e8cd4ebef26c3e9d6f3f) fix(ci): observe daemon health through native Unix HTTP
- [102ab82](https://github.com/InstruktAI/TeleClaude/commit/102ab823ee8ffd45ac384ad01dda11946784a1cb) docs(quality): permit real command tools in the smoke harness [skip ci]
- [0181cc8](https://github.com/InstruktAI/TeleClaude/commit/0181cc83d5473be86c41086fff4e98a589f84e0c) docs(quality): prefer Python smoke orchestration [skip ci]
- [2bac3a4](https://github.com/InstruktAI/TeleClaude/commit/2bac3a443c50779184e49ebc18b30a24f2e987e2) fix(ci): send project job patch in the public input shape
- [56448ad](https://github.com/InstruktAI/TeleClaude/commit/56448ad9024031b779b22ef0c2e1cb7b3688c13a) docs(quality): clarify the public command boundary [skip ci]
- [c1aa1a0](https://github.com/InstruktAI/TeleClaude/commit/c1aa1a0b074a477b4d70a6ed2ffcf109cb210e01) fix(ci): enforce a total native health observation deadline
- [520b2df](https://github.com/InstruktAI/TeleClaude/commit/520b2df94dc8503ee1f64fd7d593103ce86c4b1d) docs(quality): state the current verification policy directly [skip ci]
- [d609677](https://github.com/InstruktAI/TeleClaude/commit/d6096771f9c214e10c25673cb2c8b11c689fb51c) fix: doc+code reviewer thinking mode upgrade for review-commits [skip ci]
- [57a179a](https://github.com/InstruktAI/TeleClaude/commit/57a179a1cdf8af6e2b3c87eab0d8b80380317ea7) fix(ci): bind unauthorized writes to command-clearance refusal
- [9dc24b2](https://github.com/InstruktAI/TeleClaude/commit/9dc24b278787d27933bc56d720481d9ed6bc7370) docs(config): state the null computer-name caveat [skip ci]
- [ad13f42](https://github.com/InstruktAI/TeleClaude/commit/ad13f42e0bf2a8393a2094ad30b2cc76f47e61b5) feat(release): support chosen versions with complete captured commit notes
- [fff6cd4](https://github.com/InstruktAI/TeleClaude/commit/fff6cd4f75521587f0b79dedf34a1cfdde1e84b5) chore(docs): reconcile lifecycle markers for release-manual-version-and-commit-notes
- [40c188b](https://github.com/InstruktAI/TeleClaude/commit/40c188b0b31448f2e5310f5cb5fe9705aa934371) fix(config): refuse invalid machine candidates through safe public diagnostics
- [fba4e11](https://github.com/InstruktAI/TeleClaude/commit/fba4e1101e981a43a85580cb3fc1e0bf3cb11659) chore(config): migrate teleclaude.yml to configuration version 21
- [513ebc6](https://github.com/InstruktAI/TeleClaude/commit/513ebc6ac62c51852d1502a2e9f9476faa60af6e) perf(install): expose stage timing without changing execution order
- [9218b59](https://github.com/InstruktAI/TeleClaude/commit/9218b5951850111edb470dbd02c430f9ef0e20fb) fix(acceptance): retain refusal evidence across state readback
- [399748a](https://github.com/InstruktAI/TeleClaude/commit/399748a39d7436582ae4ac52df529dae67477c1f) perf(install): reuse retention checks and skip current Prettier
- [fc887ca](https://github.com/InstruktAI/TeleClaude/commit/fc887ca62ba54ddce35d904fcef216a0552a64c1) fix(install): make stage timing structured and opt-in
- [b3894a1](https://github.com/InstruktAI/TeleClaude/commit/b3894a10d419c619d28ba8d2970c5d13b0eeb44e) perf(install): avoid impossible documentation layout substitutions
- [a64dfc3](https://github.com/InstruktAI/TeleClaude/commit/a64dfc356a5141f8994935e9cf593d0682fe021d) refactor(install): centralize logging configuration and rewrite prefixes
- [571139e](https://github.com/InstruktAI/TeleClaude/commit/571139e9cf46055af4aebf1e3e6bf005b8ac143c) test(acceptance): bind RA11 to captured safe schema refusal
- [4f3b28c](https://github.com/InstruktAI/TeleClaude/commit/4f3b28ccd46cab3ddb86f587fc1dd62fa4da2b83) feat(agent-runtime): deliver neutral supervised silence observations
- [6e2faa0](https://github.com/InstruktAI/TeleClaude/commit/6e2faa0daf449e541b3f0113c46feaf8bb886de3) fix(agent-runtime): align watchdog notifier keyword protocol
- [bb140ef](https://github.com/InstruktAI/TeleClaude/commit/bb140ef03d4445d559bb52c6118c69ed5b54642c) chore(docs): reconcile lifecycle markers for supervised-silence-observations
- [84cfb0f](https://github.com/InstruktAI/TeleClaude/commit/84cfb0f23c43205209dbbbca20e8e5afe6a629b5) fix(agent-runtime): return truthful session update outcomes
- [b569ffc](https://github.com/InstruktAI/TeleClaude/commit/b569ffc2ba47db5de6aead883ebd9b2fe548c635) docs(procedures): define hook-delivered activation contracts [skip ci]
- [88cfebf](https://github.com/InstruktAI/TeleClaude/commit/88cfebf61ff46f112c8d63f2e84e069c608c5b78) docs(procedures): order event persistence before activation bootstrap [skip ci]
- [0cbc55e](https://github.com/InstruktAI/TeleClaude/commit/0cbc55e79254ed99ec55bee69deec507065b6078) docs(procedures): keep shared instruction dependencies portable [skip ci]
- [02e83dd](https://github.com/InstruktAI/TeleClaude/commit/02e83ddd40a37e52ce425440940eaf66c380f43c) fix(ci): bind sandbox image checks to the validated source revision
- [9c94969](https://github.com/InstruktAI/TeleClaude/commit/9c94969a7023c1b046eea8e79bad594b163764d6) docs(procedures): align owning domain contracts with event delivery [skip ci]
- [ee586cf](https://github.com/InstruktAI/TeleClaude/commit/ee586cf6dec761f71d5c92d745026b7fa35b5780) fix(ci): refuse historical publishers without explicit source identity
- [71c6924](https://github.com/InstruktAI/TeleClaude/commit/71c692499b4c03b9dcd33fb46981eb63d9ccd85e) docs(procedures): bound initialization and continuation semantics [skip ci]
- [5ca76c1](https://github.com/InstruktAI/TeleClaude/commit/5ca76c17cdf9fb67aed78a4e70a666db375ea67b) docs(config): distinguish schema error detail from surfaced diagnostics
- [b18a5bc](https://github.com/InstruktAI/TeleClaude/commit/b18a5bc3ff1ba2f0a877f2ad8c798117a5f55ffb) perf(context): resolve publication declarations once per run
- [596f05d](https://github.com/InstruktAI/TeleClaude/commit/596f05dc496fcd2f1530d9ade80acecd2fd1f811) fix(release): bind controller roots to the job temporary parent
- [50f92db](https://github.com/InstruktAI/TeleClaude/commit/50f92db9ce70d83530fd53902409dd16939b157c) fix(config): parse boolean values and resolve reads within the selected subject
- [cec1b04](https://github.com/InstruktAI/TeleClaude/commit/cec1b0420910d40378453756e148a6a1a6018543) docs(config): state the person read shape without rationale
- [44448a1](https://github.com/InstruktAI/TeleClaude/commit/44448a1e03fd406f9c79a8c9eb73ebf71bc78933) fix(release): install both pinned age command-line tools
- [f8a8df9](https://github.com/InstruktAI/TeleClaude/commit/f8a8df96ff3ef7808f842cf35dbd1c97748ae8e1) fix(ci): delegate age setup to its typed module entrypoint
- [b7cb1d7](https://github.com/InstruktAI/TeleClaude/commit/b7cb1d776003dcbeaa55e8460bc85322e3040661) feat(agent-runtime): deliver procedure events through governed hooks
- [65404ab](https://github.com/InstruktAI/TeleClaude/commit/65404ab197b2590859a1b5635d4ac7830c9e8942) chore(docs): reconcile lifecycle markers for procedure-event-delivery
- [4d5f872](https://github.com/InstruktAI/TeleClaude/commit/4d5f872f317e9b5ee9405444f07c594d391aa2c7) fix(release): create private inspector state within the privileged boundary
- [6c8a0da](https://github.com/InstruktAI/TeleClaude/commit/6c8a0da1b74ed4cce2bfa27abad49bdbd6dda293) fix(release): encode isolated launcher environments as valid JSON
- [d67d630](https://github.com/InstruktAI/TeleClaude/commit/d67d63065ce4054e20aa9a9424fb17dca6e62009) fix(release): preserve provider stdin across isolated launcher exec
- [afeeade](https://github.com/InstruktAI/TeleClaude/commit/afeeadee3b97558c9cd7ff9a897115a96f2059c8) fix(release): preserve private config mode and check report paths with privilege
- [89107a1](https://github.com/InstruktAI/TeleClaude/commit/89107a1f049eab679fb5d7f4ae45fad68710632b) docs(release): bound controller diagnostics to covered catch chains
- [aab824d](https://github.com/InstruktAI/TeleClaude/commit/aab824d5290a8c4245d25babb41a614508e3c148) fix(release): hand off producer-owned checkpoint upload directories
- [de9c64a](https://github.com/InstruktAI/TeleClaude/commit/de9c64a116361229ef6faee539e6eeae3357eb91) fix(release): retain Claude stderr when early output cannot be parsed
- [46f81db](https://github.com/InstruktAI/TeleClaude/commit/46f81db78b77b0b2dd6c45fb4fdeac45be68fa12) docs(memory): prepare session-owned conversation extraction [skip ci]
- [a3dd944](https://github.com/InstruktAI/TeleClaude/commit/a3dd9442a4f382158c7679c9c8d78214b8a91f91) docs(memory): align pipeline consumers with pending contract [skip ci]
- [61ddb44](https://github.com/InstruktAI/TeleClaude/commit/61ddb446f718cf6dc1a6f0c4be20ffa28b9fb8bc) docs(memory): reconcile reviewed extraction contract conflicts [skip ci]
- [bdebe75](https://github.com/InstruktAI/TeleClaude/commit/bdebe75836a6c7b02e8ea0afe31d608ea0c218a7) docs(mirrors): rederive extraction spec from its actual owners [skip ci]
- [3d22ed1](https://github.com/InstruktAI/TeleClaude/commit/3d22ed1134ab505794a3018eff64ddbc41efbdd7) docs(mirrors): respect runtime-specific native identity conventions [skip ci]
- [19bdc46](https://github.com/InstruktAI/TeleClaude/commit/19bdc462df007bdf69347234e4a2241656d1f8e3) fix(release): validate recipient fingerprints in their canonical digest form
- [a16d016](https://github.com/InstruktAI/TeleClaude/commit/a16d01676cb57c59022957a9866c68cc2c27376c) docs(acceptance): add archived-history and curation-refusal journeys [skip ci]
- [ea20a4f](https://github.com/InstruktAI/TeleClaude/commit/ea20a4fb99b6a5fe6dcdaafc65485002912f3b9f) fix(release): stage controller-owned launcher outside private checkout ancestry
- [f411ffe](https://github.com/InstruktAI/TeleClaude/commit/f411ffec109ad6143ef1df795ef894c0369fb443) docs(acceptance): state the non-procedure caller in the curation refusal journey [skip ci]
- [89805e3](https://github.com/InstruktAI/TeleClaude/commit/89805e3aa6e54bb3dd88f7a3f21b4f7bfb4c9ac5) docs(mirrors): separate coverage readiness from source completeness [skip ci]
- [fbd8b91](https://github.com/InstruktAI/TeleClaude/commit/fbd8b91384c2a9eacaf994dd69e928c523616669) docs(memory): gate pending extraction on mirror readiness, not completeness [skip ci]
- [e1193c4](https://github.com/InstruktAI/TeleClaude/commit/e1193c4cb98d228ea355d1d5c803096bc350910e) fix(release): bootstrap isolated inspectors under a shared namespace
- [48b02be](https://github.com/InstruktAI/TeleClaude/commit/48b02be8f2478d65e90eb74262fe114412ae8246) fix(release): retain bounded Codex controller operation diagnostics
- [2f1a6a2](https://github.com/InstruktAI/TeleClaude/commit/2f1a6a2314d02ab538f854cf29d4038e904c7a46) feat(memory): preserve conversation identity and incremental extraction
- [0dde5b1](https://github.com/InstruktAI/TeleClaude/commit/0dde5b10134a23752ffcf7c7fc36b76dea9c93fb) chore(docs): reconcile lifecycle markers for conversation-memory-continuity
- [5e86319](https://github.com/InstruktAI/TeleClaude/commit/5e863196513b0b051afa4fdc9e0d1eeadc625ee4) refactor(db): isolate pending message deletion persistence
- [7369a04](https://github.com/InstruktAI/TeleClaude/commit/7369a049184c7531e07d4014ef84594ad7f2f2d6) refactor(agent-runtime): isolate in-place restart and shared stop barrier
- [9187cf0](https://github.com/InstruktAI/TeleClaude/commit/9187cf058bb5356e9a346924211a11abf590231c) fix(packaging): bound Python support to the installable locked graph
- [2317180](https://github.com/InstruktAI/TeleClaude/commit/2317180f814f54936ef4ffbe612108273d5fdca3) docs(conversations): make channel designation govern continuity [skip ci]
- [bc8f92b](https://github.com/InstruktAI/TeleClaude/commit/bc8f92b135506e60cd70635434bf7290f4244e53) fix(release): pass Claude inspection prompts through stdin
- [f8ce801](https://github.com/InstruktAI/TeleClaude/commit/f8ce80150d171ef1cf6bcca3b509a2e47c429b83) fix(release): capture Codex auth independently of its final report
- [e3286e8](https://github.com/InstruktAI/TeleClaude/commit/e3286e817b4572d39d13750182f85d45a6ac2608) fix(release): select native Codex exec before inspection flags
- [eb30e78](https://github.com/InstruktAI/TeleClaude/commit/eb30e7821604299da0457779710b6d8e8180ce5a) docs(conversations): route shared Team input through master ownership [skip ci]
- [716a477](https://github.com/InstruktAI/TeleClaude/commit/716a477081ce12d4e3f846c4d27c5ab9af07714e) docs(conversations): complete designation and mixed-input contracts [skip ci]
- [862fb3e](https://github.com/InstruktAI/TeleClaude/commit/862fb3eb37fc550f816a3e88e4e5a3130f25b5f2) fix(release): retain verified reseed authority for settled descendants
- [0aefe46](https://github.com/InstruktAI/TeleClaude/commit/0aefe46990dab3e829710a4a806211e7d48d6fa4) fix: job config [skip ci]
- [c396b9d](https://github.com/InstruktAI/TeleClaude/commit/c396b9da47c8e85140d011625231639137ab8f9f) docs(conversations): carry Discord DM attachments through the conversation seam [skip ci]
- [7aeeb00](https://github.com/InstruktAI/TeleClaude/commit/7aeeb0069c49c5da6774cc3efc6b664abdf03bb8) fix(config): one reference grammar and one effective view for every configuration surface
- [9e5741e](https://github.com/InstruktAI/TeleClaude/commit/9e5741eea58d4084a16bb4680920fdb5eecd2905) fix(release): validate Claude native structured report events
- [69c2d3b](https://github.com/InstruktAI/TeleClaude/commit/69c2d3b59fa74f1fbac974d1bc5d876423c4080c) docs(routing): contract computer-addressed execution through one boundary relay
- [50617f1](https://github.com/InstruktAI/TeleClaude/commit/50617f1a250c6f6f4fc656e54f779800191e1291) fix(config): typed effective values fail fast and saves compare by type
- [b21d166](https://github.com/InstruktAI/TeleClaude/commit/b21d166148ebec0aa08343c85c59e7efd5f66e6e) docs(routing): relay carries the principal as identity and keeps remote artifact state rules
- [60b98c6](https://github.com/InstruktAI/TeleClaude/commit/60b98c6806d524cf83d861325b6af9139d7f9c0a) fix(config): convert resolved values through the full declared field type
- [5d56025](https://github.com/InstruktAI/TeleClaude/commit/5d56025f62aeefe3446db89ee2077d668131632a) docs(tui): pend computer-scoped Sessions-view row actions and the owner&#x27;s working-directory refusal [skip ci]
- [a507044](https://github.com/InstruktAI/TeleClaude/commit/a507044100abccd5b0c20904181fedf1b59e4ded) docs(identity): a carried role is projection, never authority; the relay carries principal and caller address only
- [9deb415](https://github.com/InstruktAI/TeleClaude/commit/9deb4155b7b4e85cbf129d2ebcc10eaf7ff25ce0) docs(identity): restore the authorization contract to its standing text pending independent repair
- [f65ad7e](https://github.com/InstruktAI/TeleClaude/commit/f65ad7e12229cb24fb6c12ed05ade0db6db16163) docs(identity): a carried role is projection, never authority — repair the cross-computer authorization contract to match the live message path
- [1ce6ee4](https://github.com/InstruktAI/TeleClaude/commit/1ce6ee4a6a5dc6e3ead45830cdabec7c1fd191c8) docs(governance): name consumer restatement and close it by removal in authoring and review lanes
- [f56c0b0](https://github.com/InstruktAI/TeleClaude/commit/f56c0b0b7a8c6833564b32873fa623007d273f63) docs(routing): address configuration commands to their owning computer [skip ci]
- [b02d876](https://github.com/InstruktAI/TeleClaude/commit/b02d8762e0b0ab91940a6ddd14e2f68b372099e9) docs(governance): citation rule covers Gherkin; record the consumer-restatement process change
- [f36452e](https://github.com/InstruktAI/TeleClaude/commit/f36452ec8e6927509e40d459619e6faad4dacf05) docs(routing): reduce computer-addressed specs to the rules their contexts own [skip ci]
- [abe0f6b](https://github.com/InstruktAI/TeleClaude/commit/abe0f6b7faca784411bd50730611d640e0b68f44) docs(config): retire wizard and chip-color restatements of the schema-driven config TUI
- [2dad40f](https://github.com/InstruktAI/TeleClaude/commit/2dad40fa00a2e3f730b507a50740118ea3e191a7) docs(history): drop remote-reach restatement from history search and role-scoped access [skip ci]
- [42531c8](https://github.com/InstruktAI/TeleClaude/commit/42531c8d277ad1258c82962d3ab259878447b33b) docs(tui): retire UC-SVIS-5, owned by procedure-standing-agent UC-PSA23 [skip ci]
- [dce306c](https://github.com/InstruktAI/TeleClaude/commit/dce306ce91d09c320c3962de63ebc735ffb2f2e1) docs(workflow): retire UC-WM30, the preparation-view restatement of the manual hold rule [skip ci]
- [9fe805e](https://github.com/InstruktAI/TeleClaude/commit/9fe805eecb426508d8426028710eae0199b4f498) docs(agent-restart): retire UC-AR5 and UC-AR20 as consumer restatement [skip ci]
- [24acd9b](https://github.com/InstruktAI/TeleClaude/commit/24acd9b7d68bc07ed05a75b732e8725aff57ea51) docs(history): retire relay restatement from history federation and repoint its citers to the owners [skip ci]
- [1ea6664](https://github.com/InstruktAI/TeleClaude/commit/1ea66645ebdd14d5c35eec46cc0e4e71b5606c13) docs(tui): trim consumer restatement from UC-SACT-4 and pending UC-SACT-9 [skip ci]
- [92eebac](https://github.com/InstruktAI/TeleClaude/commit/92eebacb07f20467f5f00102d20be983841b1e6d) docs(workflow): drop work-orchestrator child ending across computers from UC-WSM5 [skip ci]
- [342ffce](https://github.com/InstruktAI/TeleClaude/commit/342ffce15c7e3e93967d862df32a4b1cfc9396a5) docs(routing): leave refusal content to the workflow owner [skip ci]
- [effa418](https://github.com/InstruktAI/TeleClaude/commit/effa418cc5da14bdb2fc6e93b1dd302248293447) docs(agent-handoff): retire UC-AH9 as consumer restatement [skip ci]
- [0437d93](https://github.com/InstruktAI/TeleClaude/commit/0437d93ddbe5d93dabd8a158b8e7b2315fa158b9) docs(identity): trim cross-computer decisions XCA owns out of UC-CCS7 and UC-CCA4 [skip ci]
- [68b63eb](https://github.com/InstruktAI/TeleClaude/commit/68b63eb7f09e135c9e7dbd47c4fae059344cfbec) docs(tui): reduce preparation lifecycle actions to the rules the view owns [skip ci]
- [aed2587](https://github.com/InstruktAI/TeleClaude/commit/aed2587e284f3d3e0257b441848b8e969d3ef348) fix(release): correlate rejected formatter retries with native outcomes
- [22c52b9](https://github.com/InstruktAI/TeleClaude/commit/22c52b9e0a6e1e0ad69980b7ec2db2746942888a) docs(session-input-delivery): retire UC-SID3 and drop the no-computer clause [skip ci]
- [9e39c70](https://github.com/InstruktAI/TeleClaude/commit/9e39c70279be00b9382bb0f03fe7909afcefaee2) docs(identity): retire UC-XCA5, the unreachable-computer rule computer-addressed execution owns [skip ci]
- [2a6741a](https://github.com/InstruktAI/TeleClaude/commit/2a6741ac5330b007ab5af91c80ce8eef8d998293) docs(tui): retire UC-TUI-PL4 and drop project-list restatements of adoption [skip ci]
- [e9a6f1c](https://github.com/InstruktAI/TeleClaude/commit/e9a6f1c308881f185dbf69f24a7f1dbd71967dc4) docs(session-inspection): retire UC-SI7 as consumer restatement [skip ci]
- [f2c04b6](https://github.com/InstruktAI/TeleClaude/commit/f2c04b6d5157832b7dd01cc274d281fa31537c0d) docs(workflow): drop operation-outcome wake restatements from todo removal [skip ci]
- [70cc995](https://github.com/InstruktAI/TeleClaude/commit/70cc995df63bfe04a178ae660649ef46a3edee01) docs(interactive-command-input): retire UC-ICI7 as consumer restatement [skip ci]
- [ed9077d](https://github.com/InstruktAI/TeleClaude/commit/ed9077d3004cf60ac9ab8ae5f76cbaed207f31f6) docs(session-subscriptions): drop cross-computer clauses restated from UC-SS3 and UC-SS9 [skip ci]
- [e9261b2](https://github.com/InstruktAI/TeleClaude/commit/e9261b2a1954525fb266137d6c69b2a7456907ef) docs(supervisory-silence): retire UC-SSO7 and drop the restated capability sentence [skip ci]
- [49f7242](https://github.com/InstruktAI/TeleClaude/commit/49f72425304e5249c7a0e4b67c949ae9be307558) docs(session-transcript-retrieval): drop the computer-selector routing sentence [skip ci]
- [5e7a3c0](https://github.com/InstruktAI/TeleClaude/commit/5e7a3c0baa96eb21ad5e94a5645605fe60d5a1b1) docs(session-lifecycle): drop remote-creation and remote-listing restatements [skip ci]
- [609eacc](https://github.com/InstruktAI/TeleClaude/commit/609eaccd7e3d851630687048bf669a46a7e293ed) docs(operation-outcomes): trim UC-DO7 to the outcome crossing it owns [skip ci]
- [04cf6e5](https://github.com/InstruktAI/TeleClaude/commit/04cf6e5aadbc513b9beaa2eab56a9f336ffc222d) docs(standing-agent): retire UC-PSA24 and point the unattended listing rule at UC-SL58 [skip ci]
- [31de77b](https://github.com/InstruktAI/TeleClaude/commit/31de77b485238186364f6d9ae0f00e667e5290d8) docs(tui): UC-PLA-7 asserts only the identity the view addresses [skip ci]
- [e83982c](https://github.com/InstruktAI/TeleClaude/commit/e83982cddbc4914792a6b911d276e3a498d8675f) docs(conversations): prepare master-owned public entry and bot retirement [skip ci]
- [ea2ad1f](https://github.com/InstruktAI/TeleClaude/commit/ea2ad1f957297d6f6ade55741d07e1a0eb23cdee) feat(conversation): continue designated channels through shared core entry
- [be18c12](https://github.com/InstruktAI/TeleClaude/commit/be18c1270deef1daf8c4cf089c3f509fc8964c56) chore(docs): reconcile lifecycle markers for designated-channel-continuity
- [6b31a19](https://github.com/InstruktAI/TeleClaude/commit/6b31a193c5a6711d5835f4395085cf4e33245161) docs(history): local mirrors join a federated search only when the local computer is named
- [3fc6cc4](https://github.com/InstruktAI/TeleClaude/commit/3fc6cc42654fa63206f761cdc99169f0827dc2e0) docs(history): the fan-out use case admits local mirrors when the local computer is named
- [ffe383f](https://github.com/InstruktAI/TeleClaude/commit/ffe383fb8a3bff7005430070d079faaf3c5c68eb) feat(release): probe native sandbox before auth restoration
- [0de00d7](https://github.com/InstruktAI/TeleClaude/commit/0de00d7918b4c71ac0cce804b73ab37657bfc32f) docs(routing): owner admission, negotiated relay and owner-local surfaces for computer-addressed requests [skip ci]
- [70312e3](https://github.com/InstruktAI/TeleClaude/commit/70312e3911626a33a0d0e3dc5e9e6f3d55242e09) perf(context): deploy rendered artifacts without Prettier
- [a0e7519](https://github.com/InstruktAI/TeleClaude/commit/a0e75190607cdba6daa2a70ce51f8c49b94e3ae5) docs(routing): owner trusts the carried command as it trusts the principal [skip ci]
- [4e74e7a](https://github.com/InstruktAI/TeleClaude/commit/4e74e7a1f8e34ef729623f858403f9db2f293f44) docs(routing): an addressed project command acts on the same registered project there [skip ci]
- [1a75654](https://github.com/InstruktAI/TeleClaude/commit/1a756542743df1d73d93b90761b31f1bf1bde94f) refactor(release): type preflight diagnostic vocabularies
- [753886b](https://github.com/InstruktAI/TeleClaude/commit/753886b86482741b2d060a624aa058a85f5cfd50) docs(routing): the addressed computer rejects what it cannot run; direct links stay put [skip ci]
- [37e5d3a](https://github.com/InstruktAI/TeleClaude/commit/37e5d3a16906d769946785bf83f5afeee865e5e9) docs(config): declare master-scoped provider sections and master-executed person delivery [skip ci]
- [e28fbdd](https://github.com/InstruktAI/TeleClaude/commit/e28fbdd134c2b2e8e3a165e16654345acf837983) docs(routing): send to any computer this one knows; keep body-addressed sessions crossing [skip ci]
- [61e4acd](https://github.com/InstruktAI/TeleClaude/commit/61e4acd516c5f595765bfa7a757d50f4cdc24d93) docs(routing): report an offline computer as one that did not answer [skip ci]
- [5f5a7bb](https://github.com/InstruktAI/TeleClaude/commit/5f5a7bb3791a0913d1358c82abd20bcbd6b942c6) docs(messaging): drop UC-PAM7, a restatement of the messaging spec&#x27;s master-send rule [skip ci]
- [5a0533f](https://github.com/InstruktAI/TeleClaude/commit/5a0533f787828754e1298f34665eccce3b8dbd00) docs(routing): separate an offline peer from a slow one; relay commandless known acts [skip ci]
- [5c55723](https://github.com/InstruktAI/TeleClaude/commit/5c55723b6a7f2f5fecb3ebe77b11f381ddb29df2) docs(conversation-entry): retire the cutover procedure with the bot retirement [skip ci]
- [29bafda](https://github.com/InstruktAI/TeleClaude/commit/29bafdab353515ab7ba0b48fcd19342b095937ae) docs(conversations): state declared-master receiver and provider-write authority under master conflict [skip ci]
- [ee8d214](https://github.com/InstruktAI/TeleClaude/commit/ee8d21471c44b1ae5bb90a93b08f57dbcb33a23a) docs(routing): an unanswered relay is an unknown outcome, not a work refusal [skip ci]
- [752072b](https://github.com/InstruktAI/TeleClaude/commit/752072bacceb6d8a9fb0cf909d10a8c15050bedd) docs(conversations): keep shared Discord writes with the unique master under conflict [skip ci]
- [48bf67b](https://github.com/InstruktAI/TeleClaude/commit/48bf67bb10827d6b82f174b7474ae6acbdb5a27e) perf(context): reuse publisher inventory within publication
- [1321a9f](https://github.com/InstruktAI/TeleClaude/commit/1321a9f360886a8cb44acd0a062cd6137eba1cb7) docs(invitations): keep UC-PI2 to the invitation store&#x27;s own guarantee [skip ci]
- [79d0200](https://github.com/InstruktAI/TeleClaude/commit/79d02003631d0ba82005d40a41b2ed5f33602a4f) fix(acceptance): provision procedure fixtures from checked source dependencies
- [317c19b](https://github.com/InstruktAI/TeleClaude/commit/317c19bafef914806abbb2a8e2426dd1f3ec70bd) docs(config): keep master scope and enabled governance to what the code can honor [skip ci]
- [8169d06](https://github.com/InstruktAI/TeleClaude/commit/8169d0643b963db5cc158ad0d1304591c2472c77) docs(conversation-entry): drop the one-off cutover procedure; name the one-off runbook anti-pattern [skip ci]
- [bc4085f](https://github.com/InstruktAI/TeleClaude/commit/bc4085f05ee70c81d6989716fbed664bbf3377fe) feat(relay): execute computer-addressed requests through one owner boundary
- [4bd875b](https://github.com/InstruktAI/TeleClaude/commit/4bd875ba712076c13a997fbd0b55b32665ead89d) chore(docs): reconcile lifecycle markers for relay-computer-addressed-requests
- [9096d9b](https://github.com/InstruktAI/TeleClaude/commit/9096d9b9c2fbf97891c5b142f6f210607d4d7366) refactor(release): inspect providers on separate native hosted jobs
- [6b3e93e](https://github.com/InstruktAI/TeleClaude/commit/6b3e93e0e9bfc0c005d73b3bc90efd36ce10e256) fix(tui): keep Sessions-view actions on their owning computer
- [cd7abf5](https://github.com/InstruktAI/TeleClaude/commit/cd7abf5a49a9fb2316ade483f9c16d7978e3cffa) chore(docs): reconcile lifecycle markers for tui-sessions-view-remote-row-assumptions
- [2bd59d3](https://github.com/InstruktAI/TeleClaude/commit/2bd59d3af208d3c4c743d05f5fdfab021f04ebb6) fix(acceptance): retain public terminal auth for fixture closure reads
- [5388692](https://github.com/InstruktAI/TeleClaude/commit/5388692b4108ae4b6f8135bc8c08c0ed107a7ced) fix(release): require completed native denial proof before auth
- [d2aadfb](https://github.com/InstruktAI/TeleClaude/commit/d2aadfbb59bcbd79144f247bef2b61c09eb0c0b9) fix(release): remove redundant nested Codex filesystem masks
- [8cfeb38](https://github.com/InstruktAI/TeleClaude/commit/8cfeb38cd964be59b82ceb2f617feae2e4c5fa3f) fix(ci): bind procedure closure snapshots to captured public framing
- [89aa536](https://github.com/InstruktAI/TeleClaude/commit/89aa5367294922bac08da666c1ccb885827a9543) feat(conversation): host public conversations and invitations on the master
- [3f3ae6c](https://github.com/InstruktAI/TeleClaude/commit/3f3ae6c7f72645a61f5ce693207b5bf60df7f84f) fix(release): check the native receipt producer as typed source
- [0a409b7](https://github.com/InstruktAI/TeleClaude/commit/0a409b7dfbec98637b43c29e864bfc6b689b40b0) fix(release): remove the redundant private TMPDIR alias mask
- [65df313](https://github.com/InstruktAI/TeleClaude/commit/65df313a9502ad4e91b63ee205967aaf7bc50b5b) Merge remote-tracking branch &#x27;origin&#x2F;main&#x27;
- [a606dce](https://github.com/InstruktAI/TeleClaude/commit/a606dce3b52360c46134275d9118915ea57b3f2a) chore(docs): reconcile lifecycle markers for master-conversation-entry
- [42cab4e](https://github.com/InstruktAI/TeleClaude/commit/42cab4e0ed0582625e4629d116d08d944a068957) fix(ci): provision the declared synthetic procedure fixture company
- [52fac17](https://github.com/InstruktAI/TeleClaude/commit/52fac1708b57ae50bba8ac35b0fc8e3647fbe71a) fix(release): retain bounded pre-auth native startup stderr
- [084caa2](https://github.com/InstruktAI/TeleClaude/commit/084caa27732869546066c57265ffc73873aca5ab) docs(config): retire the never-used break-glass Telegram alerts [skip ci]
- [00b3e2b](https://github.com/InstruktAI/TeleClaude/commit/00b3e2b4f1ebab187bdeaf76dc838caf12e7acd8) refactor(discord): split input handling by surface
- [4b193aa](https://github.com/InstruktAI/TeleClaude/commit/4b193aa11da599c197bec277385fadc0742badfb) docs(conversations): name the conversation and console planes behind Discord&#x27;s local scope [skip ci]
- [fdb886e](https://github.com/InstruktAI/TeleClaude/commit/fdb886e7c792b9065111efa3ddb9878f6f48b705) fix(release): expose only the pinned native Codex runtime file
- [32d33ab](https://github.com/InstruktAI/TeleClaude/commit/32d33abdfeb8f5c0d02eb84781b02951611d5eb1) Merge remote-tracking branch &#x27;origin&#x2F;main&#x27;
- [55c219a](https://github.com/InstruktAI/TeleClaude/commit/55c219a2a47ce3188b316ebd43986eed1497c572) refactor(release): own native architectures and denied rules once
- [15a062e](https://github.com/InstruktAI/TeleClaude/commit/15a062ed48105dabc8944244a7f9eebeba9f1848) fix(hooks): reserve stop continuations for checkpoints
- [a10fafc](https://github.com/InstruktAI/TeleClaude/commit/a10fafc31ff8543d81a054508a51fb3e5f1bf996) docs(hooks): keep delivery spec focused on its contract
- [5bda15b](https://github.com/InstruktAI/TeleClaude/commit/5bda15b226041e5fa343ee26e30b5d25e8c77e75) fix(cli): announce background maintenance after pulls
- [6ad1341](https://github.com/InstruktAI/TeleClaude/commit/6ad13419af8241ac36afe86990e31b3ab8daea45) fix(release): validate contained absolute Claude glob patterns
- [3474556](https://github.com/InstruktAI/TeleClaude/commit/34745563e3aa49adad1e4c6bdfde6def0aa928f9) fix(release): clarify bounded grouped assessment completeness
- [c4c2fe2](https://github.com/InstruktAI/TeleClaude/commit/c4c2fe217ba556aedfcd4d8f5a903c07b52af4ed) feat(config): make person-facing providers master-owned
- [b186b26](https://github.com/InstruktAI/TeleClaude/commit/b186b2673162433c2442c0cac099ec0fae628803) fix(relay): authorize computer-addressed requests at the destination
- [1d7788e](https://github.com/InstruktAI/TeleClaude/commit/1d7788e4d1b2a48ba9631dc5aee168665db612fb) Merge remote-tracking branch &#x27;origin&#x2F;main&#x27;
- [ec1ed22](https://github.com/InstruktAI/TeleClaude/commit/ec1ed22c6b66edb53d5e7d705062c96346125343) docs(identity): align governing contracts with destination authorization
- [8d3bb73](https://github.com/InstruktAI/TeleClaude/commit/8d3bb73bee702e5b106ac80c3f23facde9a7223d) chore(docs): reconcile lifecycle markers for master-owned-providers
- [4a9caba](https://github.com/InstruktAI/TeleClaude/commit/4a9caba1332ba1de54288b1bf4b2a834f07d81e6) fix(release): bound completion to version and compatibility assessment
- [fc08a91](https://github.com/InstruktAI/TeleClaude/commit/fc08a9162a352b3bf065fe9e7cf8e3c6b0c8f1e9) docs(release): retain AI summaries for explicit-version releases
- [a109b24](https://github.com/InstruktAI/TeleClaude/commit/a109b2475625e0683763e0364394a18afbd37999) fix(session-scoping): read declaration records without locking or creating paths
- [0cdf175](https://github.com/InstruktAI/TeleClaude/commit/0cdf175a506bd0c87cf811fbc4aa8b8e2bba34a7) docs(release): mark explicit-version AI summaries as pending
- [3ab6566](https://github.com/InstruktAI/TeleClaude/commit/3ab656628d03eabf5e5296cb8d80839cedd56075) fix(relay): retain destinations through client clearance
- [5ab0e1e](https://github.com/InstruktAI/TeleClaude/commit/5ab0e1eb313ae63b796e99abbdd51713ede02ba9) fix(relay): require a principal before edge forwarding
- [5c9904c](https://github.com/InstruktAI/TeleClaude/commit/5c9904cf1a1c544db3d7c8baef3558be561cbc20) feat(release): attempt optional AI summaries for explicit versions
- [1093880](https://github.com/InstruktAI/TeleClaude/commit/109388002a7a5f35f8631c5eae088cc2d9ff81fe) fix(release): isolate summary task navigation from assessment
- [3f0d895](https://github.com/InstruktAI/TeleClaude/commit/3f0d8953a28d1b9a5516399316f2d76a6f2b032d) chore(release): activate automatic publication after qualifying proof
- [fd6b9c8](https://github.com/InstruktAI/TeleClaude/commit/fd6b9c840ad045b78c6ad2b1901fc3e5b42e81d3) fix(release): own the selected-provider output key
- [77abb91](https://github.com/InstruktAI/TeleClaude/commit/77abb918730d5b858609bbe18f5b2b6edcb579f7) fix(release): own the provider attempt option token
- [b4f92ee](https://github.com/InstruktAI/TeleClaude/commit/b4f92ee10ce0dc21e3c0932a499d03b3f0bb480c) docs(context): author the pending convergence overlap and failure-reporting contract [skip ci]
- [e04c633](https://github.com/InstruktAI/TeleClaude/commit/e04c633b9c1a87bea15dcc42c7ec496965b345d2) docs(spec): name missing publishers and owner records with their registration doors
- [c0a2c15](https://github.com/InstruktAI/TeleClaude/commit/c0a2c1515ff631f2e4d9337b36e32d84228ff19a) docs(context): make the pending rollback scenario&#x27;s outcomes compatible for paths another writer changed [skip ci]
- [d9ae3c1](https://github.com/InstruktAI/TeleClaude/commit/d9ae3c112c4f0b8096a0e2d728a52fdfb09ae21f) revert(spec): withdraw per-field unregistered-referent scenarios
- [b7937af](https://github.com/InstruktAI/TeleClaude/commit/b7937af32bc663fcef71e6bd90962fd896382db8) docs(spec): resolve every named referent through one config-owned answer
- [8def26c](https://github.com/InstruktAI/TeleClaude/commit/8def26cefda4d49ea5b9c2db04dbb0849591d52c) docs(spec): add the config-owned referent-resolution contract
- [9af1235](https://github.com/InstruktAI/TeleClaude/commit/9af1235e2b49cf556075d0d5520128194f6b923f) docs(spec): type the actor in the referent-resolution scenarios
- [6edf8d7](https://github.com/InstruktAI/TeleClaude/commit/6edf8d7167adbc26f4ab530b77536085d4c61609) docs(reconciliation): place the installer&#x27;s convergence-result response with installation [skip ci]
- [caff1d8](https://github.com/InstruktAI/TeleClaude/commit/caff1d823e2443e1b6e5c397c102bfff8a495355) docs(spec): give each referent-resolution scenario one facing
- [8350291](https://github.com/InstruktAI/TeleClaude/commit/83502913c5330157d9470a789ed2e6511daefee8) docs(reconciliation): type the installer convergence-result scenarios by facing [skip ci]
- [06eb44b](https://github.com/InstruktAI/TeleClaude/commit/06eb44bb8f550d9d1601f0613addf42b49d1b152) docs(sdlc): contain every unit failure at supervision boundaries
- [8a71120](https://github.com/InstruktAI/TeleClaude/commit/8a71120cd425268523977c824dc2a557d485c737) fix(config): tier schemas accept whole ${NAME} references where loading expands them
- [8026181](https://github.com/InstruktAI/TeleClaude/commit/8026181e0bd6de926e14cb4681d2a24433fa6c53) docs(spec): carry identity alone in the new and retired referent use-case headers
- [bf9e959](https://github.com/InstruktAI/TeleClaude/commit/bf9e9598f033125772b5186be3280638e59cc1e5) docs(specs): name the agent or person who reads installer and convergence output [skip ci]
- [61c5ad4](https://github.com/InstruktAI/TeleClaude/commit/61c5ad41729f881f6e663d0f1082293bfa07eb08) docs(sdlc): state the invariant, not the rule, in the error-posture rationale
- [96d0d63](https://github.com/InstruktAI/TeleClaude/commit/96d0d63a706c5839b9e945d0006f5a3f3e82cd40) docs(config): bound schema reference acceptance to scalar fields
- [df1c2b7](https://github.com/InstruktAI/TeleClaude/commit/df1c2b746c12acb08b99f2e4be13b14d6142e923) docs(spec): add the relay regression scenario for intake survival [skip ci]
- [b6c2f8e](https://github.com/InstruktAI/TeleClaude/commit/b6c2f8ee91f09fb4c6b351d4af1f00e046d63a16) fix(release): ground semantic claims in reachable behavior
- [bfd5c49](https://github.com/InstruktAI/TeleClaude/commit/bfd5c49f040f7029a308f4e47ad992ff07877fc4) fix(config): publish the computer schema and retain its editor reference
- [96f5b22](https://github.com/InstruktAI/TeleClaude/commit/96f5b221f0b092ad84842f143eea9a90fdcd2a71) feat(config): surface unregistered referents consistently
- [6371783](https://github.com/InstruktAI/TeleClaude/commit/63717831733aef799c7b02e6b5f717a81030fb15) fix(config): honor editability tiers in schema suggestions
- [86cf6fc](https://github.com/InstruktAI/TeleClaude/commit/86cf6fcd48d809c53df243d5c6f30712a3f5f692) refactor(config): type the JSON schema value vocabulary
- [92abd75](https://github.com/InstruktAI/TeleClaude/commit/92abd7518002b61a5b342d70e8b32fcfc4dd9104) docs(orchestration): preserve stranded review-mode edits
- [bfd6c50](https://github.com/InstruktAI/TeleClaude/commit/bfd6c5063050e5b7e639e974104a552f33006b27) docs(work): preserve stranded reviewer-mode edits
- [86dcb0c](https://github.com/InstruktAI/TeleClaude/commit/86dcb0c09b0b10adfde39f6d44184836b64969ea) docs(dispatch): preserve stranded thinking-mode edits
- [f3ba60a](https://github.com/InstruktAI/TeleClaude/commit/f3ba60a9fb6269e67910bb948c3ee783572fcd9c) docs(runtime): preserve stranded commit-review mode edits
- [c1557e9](https://github.com/InstruktAI/TeleClaude/commit/c1557e9ae4a4be15ab2e4728327b1e04f24b7df8) docs(commits): preserve stranded review-routing edits
- [8306a6a](https://github.com/InstruktAI/TeleClaude/commit/8306a6aed8762adb459d0584ea37dbc2d0004024) docs(jobs): preserve stranded schedule-default edits
- [d2fecf1](https://github.com/InstruktAI/TeleClaude/commit/d2fecf10cdb97b2e5e1bb392c4682b8522fb115a) fix(acceptance): verify memory refusal state and complete terminal frames
- [af4fc30](https://github.com/InstruktAI/TeleClaude/commit/af4fc30f4f67b73e039512ca91575b28ac2ea6d4) Merge remote-tracking branch &#x27;origin&#x2F;main&#x27;
- [ce6ab73](https://github.com/InstruktAI/TeleClaude/commit/ce6ab73c12af7da1f58e3a89d12103d883fd7e19) fix(acceptance): describe the observed memory-list mismatch
- [ff55e58](https://github.com/InstruktAI/TeleClaude/commit/ff55e586b04579286e3f5ea822374a1693a1b5e4) docs(review): align preserved clauses with current routing and job schema
- [8853e2a](https://github.com/InstruktAI/TeleClaude/commit/8853e2a24fd79d00dd1a89ad70058803fadf6fcd) docs(jobs): point execution defaults at their source owners

**Full diff:** [v0.7.0...v0.8.0](https://github.com/InstruktAI/TeleClaude/compare/v0.7.0...v0.8.0)

## [0.7.0] - 2026-10-11

This release establishes a current-state baseline. It does not claim a complete historical compatibility audit.

Initial current-state baseline for the rebuilt release pipeline. This release certifies the captured source through final-candidate lint and the complete disposable macOS installer harness. It establishes the comparison baseline for subsequent releases; it does not claim an exhaustive assessment of the historical interval since v0.6.1.

**Full diff:** [v0.6.1...v0.7.0](https://github.com/InstruktAI/TeleClaude/compare/v0.6.1...v0.7.0)

## [0.6.1] - 2026-04-18

# Release Notes

## Patch — Internal quality pipeline fix

### Bug Fixes

- **quality**: Fixed language-aware file dispatch in the lint, format, and test pipelines. Explicit file lists are now correctly routed by language rather than relying on broad glob patterns.

### Internal

- Added unit tests for lint command handler, test command handler, and format module covering the new dispatch behavior.
- Extracted shared scoping logic into `quality/scope.py`.

**Full diff:** [v0.6.0...v0.6.1](https://github.com/InstruktAI/TeleClaude/compare/v0.6.0...v0.6.1)

## [0.6.0] - 2026-04-18

## Release Notes

### New Features

- **`telec code` command group**: New top-level namespace for code quality and commit tooling. Includes `lint`, `test`, `format`, `changed`, and `commit` subcommands with session-scoping support and `--all` flag to bypass scoping.
- **Project config fields**: Added `frontend_root`, `language`, `languages`, and `project_slug` to ProjectConfig for richer project metadata.
- **`-c` short alias for `--computer`**: Available on `sessions start`, `sessions run`, `sessions end`, `projects list`, `history search`, and `history show`.
- **Changelog generation**: Added changelog generation and backfill for all releases.
- **Session scoping**: Centralized per-session file ownership tracking across agents.
- **Project catalog**: Introduced project catalog service with per-project job orchestration.

### Breaking Changes

- **`telec todo verify-artifacts` removed**: Artifact verification is now integrated into the lifecycle pipeline.
- **`telec todo mark-phase` reworked**: Now takes a single `--phase` flag matching PreparePhase or WorkPhase enum members. Previous `--target`, `--status`, and `--force` flags removed.
- **`telec todo stamp --build` removed**: Build status stamping replaced by lifecycle-driven state transitions. New `--phase` flag required with `--verdict`. Added `--specs-built` and `--finalize-ready` markers.

### Improvements

- Pre-commit hooks routed through `telec code lint --step` for consistent quality gating.
- `telec todo from-main` now auto-commits worktree handoff and dispatches lifecycle router.
- Conversation delivery state machine for reliable output routing.
- Authoritative phase fields for prepare and work lifecycles.
- Legacy filesystem-based todo storage eradicated in favor of DB-only.

### Fixes

- Fixed session scoping to preserve dotfile paths and intersect with git-dirty files.
- Fixed adapter origin hint consumption to prevent duplicate processing.
- Restored pre-commit format restaging for tmux and headless parity.
- Fixed projection watermark persistence and next-machine updates.
- Fixed caller identity resolution from API auth instead of filesystem.
- Fixed CLI handler resolution to use invocation cwd, not process cwd.

### Added

- **CLI:** `telec code` — New command group with subcommands: lint (--step, --all), test (--expensive, --all), format (--all), changed, commit (-m)
- **CLI:** `telec code lint` — Run language-aware lint pipeline with --step and --all flags
- **CLI:** `telec code test` — Run language-aware test suite with --expensive and --all flags
- **CLI:** `telec code format` — Run language-aware code formatter with --all flag
- **CLI:** `telec code changed` — List session-scoped changed files
- **CLI:** `telec code commit` — Stage session-scoped files, lint, format, and commit with -m flag
- **CONFIG:** `frontend_root` — New optional string field on ProjectConfig
- **CONFIG:** `language` — New optional string field on ProjectConfig
- **CONFIG:** `languages` — New array field on ProjectConfig
- **CONFIG:** `project_slug` — New optional string field on ProjectConfig

### Changed

- **CLI:** `telec todo mark-phase` — Reworked to operator override with single --phase flag; removed --target, --status, --force flags
- **CLI:** `telec todo stamp` — Added --phase, --specs-built, --finalize-ready flags; added changes_requested verdict; removed --build flag; description updated
- **CLI:** `telec todo from-main` — Notes updated: worktree handoff is now auto-committed with lifecycle router dispatch
- **CLI:** `telec init` — Description and notes updated to reflect new project plumbing language
- **CLI:** `--computer flag` — Added -c short alias across sessions start, sessions run, sessions end, projects list, history search, history show
- **CLI:** `telec config patch` — Added --yaml (-y) flag documentation
- **CLI:** `telec sessions start` — Added `-c` as a short alias for `--computer`.
- **CLI:** `telec sessions run` — Added `-c` as a short alias for `--computer`.
- **CLI:** `telec sessions end` — Added `-c` as a short alias for `--computer`.
- **CLI:** `telec projects list` — Added `-c` as a short alias for `--computer`.
- **CLI:** `telec history search` — Added `-c` as a short alias for `--computer`.
- **CLI:** `telec history show` — Added `-c` as a short alias for `--computer`.

### Removed

- **CLI:** `telec todo verify-artifacts` — Command removed entirely

**Full diff:** [v0.5.0...v0.6.0](https://github.com/InstruktAI/TeleClaude/compare/v0.5.0...v0.6.0)

## [0.5.0] - 2026-04-10

### Added

- **todos.db:** SQLite-backed todo state store replaces filesystem `todos/` — state, artifacts, roadmap, and delivered entries all live in a per-project database
- **todos.db:** CLI handlers for `todo show`, `todo artifacts read/write/list`, `todo stamp`, with API routes to match
- **todos.db:** UUID primary keys and delivered slug reuse, filesystem-to-DB migration script
- **web-tui:** Two-panel TUI layout with session tree and keyboard navigation
- **web-tui:** Preparation, configuration, and jobs views
- **identity:** Unified identity resolution across all session origins (terminal, web, adapters, daemon)
- **output-delivery:** Adapter-owned output pull architecture replacing scattered output routing
- **memory-extraction:** Session memory extraction pipeline
- **chiptunes:** SID music player with HVSC song duration lookup and fade-out
- **chiptunes:** Stop button, dislike button for filtering unwanted songs
- **lint:** Scoped lint, test, and type-check to session-touched files in agent sessions
- **cli:** `--draft` and `--prepped` flags for `telec todo dump`
- **cli:** Register `todo read/write/stamp/artifacts` in CLI surface
- **adapters:** GFM markdown split engine and flavor-routed overflow for long messages
- **listeners:** One-shot listener support with auto-registration on plain send
- **reflection:** User input reflection, output formatting, and agent rendering
- **agent-cli:** Preserve TeleClaude context through Codex compaction
- **cadence:** Replace cursor-driven rendering with file-derived authority
- **activation-trigger:** Validate and surface activatable procedures in distribution
- **integration:** Surface anomalies from silent failure points to agents
- **reconcile:** Idempotent filesystem-to-DB reconciliation
- **tui:** Icebox toggle and display in preparation pane
- **tui:** Render `I:ready` label for `finalize_ready` state
- **db:** Unified SQLite access behind shared SQLAlchemy connection factory
- **jobs:** Project backup cron job for todo DB snapshot and S3 upload
- **services:** v2 service-oriented architecture scaffolding
- **events:** Route `todo_dumped` by kind via lifecycle router cartridge
- **todo-watcher:** OS-managed todo file watchers
- **docs:** Untrack `index.yaml` files — treat as generated artifacts
- **history:** Role-aware session history

### Changed

- **storage:** Migrate state machine from `todos/` filesystem to `todos.db`
- **storage:** Remove `roadmap.yaml`, `icebox.yaml`, and `delivered.yaml` — all in DB now
- **state-machine:** Per-step prerequisites and DB-native `mark_phase`
- **edge-http:** Move internal callers to HTTP edge layer
- **adapters:** Collapse `ThreadedOutputMixin` and `OutputDeliveryMixin` into `UiAdapter`
- **adapters:** Invert markdown strategy from mixin to adapter
- **identity:** Remove legacy origin metadata and simplify identity pipeline
- **session:** Dissolve `SessionMetadata`, unify origins
- **config:** Make `GlobalConfig`, `ProjectConfig`, and `PersonConfig` independent schemas
- **db:** Move main database to `~/.teleclaude/teleclaude.db`, mirrors to separate database
- **db:** Fresh initial schema with NullPool (SQLite gains nothing from connection pooling)
- **logging:** Migrate stdlib logging to `instrukt_ai_logging` across codebase
- **paths:** Eliminate all hardcoded `~/.teleclaude` paths — centralize in paths module
- **chiptunes:** Decouple player from daemon — worker owns state
- **cli:** Remove DTO alias layer, unify on `TodoDTO`
- **integration:** Replace stateful readiness projection with stateless `deployment.started` trigger
- Remove dynamic event cartridge system
- Remove launchd cron installer

### Fixed

- **hooks:** Restage formatter edits on `rc!=0` and retry pre-commit
- **hooks:** Auto-restage formatter-modified files in pre-commit wrapper
- **prepare:** Update `base_sha` in `RE_GROUNDING` to prevent infinite loop
- **prepare:** Restamp artifact digests on re-entry to prevent staleness loop
- **prepare:** Centralize worktree cwd resolution in dispatcher
- **asyncio:** Eliminate task leaks from `wait_for(event.wait())` pattern
- **output:** Restore pipeline session visibility on Discord admin lane
- **output:** Consolidate turn-break and close TOCTOU delivery race
- **integration:** Stop system prompt reflection crash
- **integration:** Propagate caller identity through integrator spawn chain
- **operations:** Preserve caller identity through daemon handoffs
- **db:** Plug SQLAlchemy engine leak, switch to NullPool
- **todos_db:** Add slug validation, remove contract-breaking fallbacks
- **todos_db:** Fix artifact_versions migration skipping tables with integer PK
- **cache:** Emit mutation signal from `TodosDb` to invalidate TUI todos cache
- **git-wrapper:** Rewrite in bash — Python startup caused process storm
- **git-wrapper:** Block blind merge resolution and sweep-add on main
- **discord:** Break threaded turn before broadcasting user input
- **telegram:** Treat `Topic_not_modified` as no-op, evict stale topic cache
- **chiptunes:** Reset position on track advance, skip CIA-timer tracks, fix prebuffer
- **chiptunes:** Fade AFTER listed duration, use SID's default subtune for duration
- **cli:** Ignore stale temp identity in `tc_tui` sessions
- **api:** Add global exception handler, fix `todo_dump` 500
- **regression:** Restore project config, doc snippets, and guardrails after blind merge
- **worktrees:** Remove symlink approach — workers need real tracked dirs
- **mirrors:** Fully separate mirrors from main database
- **coordinator:** Advance cadence cursor on UI input to prevent re-delivery
- **markdown:** Split at word boundaries in GFM and WhatsApp truncation

**Full diff:** [v0.4.0...v0.5.0](https://github.com/InstruktAI/TeleClaude/compare/v0.4.0...v0.5.0)

## [0.4.0] - 2026-03-21

### Added

- **cli:** `telec memories list` subcommand

### Changed

- **models:** Consolidate `ThinkingMode` — single import from `helpers/agent_types`

### Fixed

- **auth:** Remove token TTL and simplify `session_tokens` schema
- **identity:** Return empty context for API-origin sessions
- **checkpoint:** Watch all `templates/` for setup changes
- **work-machine:** Accept work-phase states in preparation precondition check

**Full diff:** [v0.3.0...v0.4.0](https://github.com/InstruktAI/TeleClaude/compare/v0.3.0...v0.4.0)

## [0.3.0] - 2026-03-20

Initial tagged release of TeleClaude.

### Added

- **Multi-agent orchestration** — Claude, Codex, and Gemini as parallel work lanes with AI consensus arbitration
- **Telegram adapter** — Full session management with topic-based threading and rich output
- **Discord adapter** — Team channels, admin lanes, and threaded output delivery
- **Session lifecycle** — Daemon-managed tmux sessions with start, send, end, restart, and revive
- **Todo/roadmap workflow** — Creative, prepare, work, and integrate lifecycle phases with state machines
- **Release automation** — AI-powered release inspection with multi-lane consensus and semver classification
- **CLI surface** — `telec` command with sessions, agents, docs, todo, roadmap, config, and auth subcommands
- **Git safety wrapper** — PATH-based binary wrapper blocking stash, checkout, restore, and reset in agent sessions
- **Agent artifact distribution** — Master file inflation, multi-agent transpilation, and runtime deployment
- **Documentation system** — Two-phase `telec docs index` / `telec docs get` with taxonomy-based snippet retrieval
- **Output polling** — Unified output delivery from agent sessions to UI adapters
- **Identity and auth** — Terminal login, session tokens for system principals, role-based authorization
- **Configuration** — Global, project, and per-person config with YAML schemas and validation
- **Event system** — Domain-scoped event schemas with cartridge-based routing
- **Integration engine** — Worktree-based integration with lease acquisition and merge verification
- **Cron runner** — Scheduled jobs with script and agent execution modes
- **Web interface** — NextAuth-based login with OTP email verification
