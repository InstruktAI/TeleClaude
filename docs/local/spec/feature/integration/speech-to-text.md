---
description: Agents turn a supplied audio file or audio URL into text through the
  computer's configured speech-to-text service chain, with a distinct outcome for
  every way it can fail.
---

# Speech To Text — Spec

## What it is

The integration context translates audio into text through the computer's
configured speech-to-text service chain: the chain that transcribes adapter
voice messages, its services tried in their configured order until one returns
a transcript. Agents reach it directly with `telec audio stt`, handing it either
an audio URL or an audio file on the computer they run on, and receive the
transcript as the command's output.

Who may run the command is decided by command clearance
(`local/projects/teleclaude/spec/feature/identity/command-clearance`); its
capability membership is in
`local/projects/teleclaude/design/cli-authorization-matrix`.

## Canonical fields

- **Source.** Exactly one of an `http` or `https` URL, or a path to a file on
  the computer that runs the command. A URL's content is fetched into storage
  the request owns and is removed when the request ends, whatever its outcome. A
  file is read where it is and is neither modified nor removed.
- **Audio as supplied.** The audio reaches the service chain as it was
  supplied, with no conversion step before it. The formats accepted are the
  formats the chain's services accept.
- **Media inspection.** Every obtained source is inspected for an audio stream
  with FFmpeg's media prober before any service is asked, and the command
  requires it. On a computer without it, the command refuses before obtaining
  the source, with a general error naming the missing tool.
- **Language.** An optional language code is passed to the chain as a hint;
  without one, each service detects the language itself.
- **Output.** The transcript is the command's standard output. The command
  records nothing: no transcription record, no session input, no stored audio.
- **Failure kinds.** Each failure ends the command with a non-zero exit status
  of its own and its reason on standard error. The CLI surface declares the
  status values.
  - _Source unavailable_ — the URL cannot be fetched (a network failure, a
    response that is not a success, a scheme other than `http`/`https`, or a
    fetch that does not complete within its limit), or the path does not name a
    readable file.
  - _Unsupported media_ — the obtained content carries no decodable audio
    stream, or its inspection does not complete within its limit.
  - _No speech-to-text service_ — the chain holds no service that can run on
    this computer: speech-to-text is disabled, or every service in the chain
    reports that it cannot run here.
  - _Transcription failed_ — the chain's services ran and none produced a
    transcript, or the chain's transcription time limit elapsed. The reason
    names each service's failure.

### Use cases

#### UC-STT1: An agent can get a transcript of audio for its person

```gherkin
Scenario Outline: Transcribe <source>
  Given an agent is acting for a person who requested a transcript of audio they can access
  When it requests a transcript from <source>
  Then it receives the transcript to fulfill that request

  Examples:
    | source                       |
    | an accessible https URL      |
    | a file on the local computer |
```

#### UC-STT2:

#### UC-STT3:

#### UC-STT4:

#### UC-STT5:

#### UC-STT6:

#### UC-STT7:

#### UC-STT8:

## Known caveats

- The command transcribes on the computer it is invoked on; it takes no
  computer argument.
- Speech-to-text is configured per computer, so the same audio can succeed on
  one computer and fail with the no-service status on another.
