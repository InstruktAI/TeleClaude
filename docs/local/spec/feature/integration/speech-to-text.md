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

#### UC-STT1:

```gherkin
Given an agent holds an https URL to an audio recording
And the computer's speech-to-text chain has a service that can run
When the agent transcribes the URL
Then the transcript of the recording is the command's output
And no copy of the fetched audio remains on the computer
```

#### UC-STT2:

```gherkin
Given an agent holds the path of an audio file on its computer
And the computer's speech-to-text chain has a service that can run
When the agent transcribes the path
Then the transcript of the file is the command's output
And the file is unchanged and still present
```

#### UC-STT3:

```gherkin
Given the computer's speech-to-text chain lists a service that cannot transcribe the audio, followed by one that can
When an agent transcribes that audio
Then the transcript from the later service is the command's output
```

#### UC-STT4:

```gherkin
Given an agent holds a URL that cannot be fetched
When the agent transcribes the URL
Then the command fails with the source-unavailable status and the reason the fetch failed
And no speech-to-text service is asked to transcribe anything
```

#### UC-STT5:

```gherkin
Given an agent holds a URL or path whose content is not audio
When the agent transcribes it
Then the command fails with the unsupported-media status
And no speech-to-text service is asked to transcribe anything
```

#### UC-STT6:

```gherkin
Given the computer's speech-to-text chain holds no service that can run on that computer
When an agent transcribes an audio file
Then the command fails with the no-service status and a reason naming why no service can run
```

#### UC-STT7:

```gherkin
Given every service in the computer's speech-to-text chain runs and fails to transcribe the audio
When an agent transcribes that audio
Then the command fails with the transcription-failed status
And the reason names each service's failure
```

#### UC-STT8:

```gherkin
Given the computer has no media prober installed
When an agent transcribes a URL or a path
Then the command refuses with a reason naming the missing tool
And no source is fetched and no speech-to-text service is asked to transcribe anything
```

## Known caveats

- The command transcribes on the computer it is invoked on; it takes no
  computer argument.
- Speech-to-text is configured per computer, so the same audio can succeed on
  one computer and fail with the no-service status on another.
