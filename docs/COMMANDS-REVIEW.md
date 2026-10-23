# Commands inside the existing SMARTINI’s Open WebUI chat

Replace JOB_ID and REVISION with the values shown above the current draft. Do not type the placeholders literally.

View the current draft and review state:

```text
review JOB_ID
```

View the speaker-labelled transcript, including turn IDs such as S000012:

```text
transcript JOB_ID
```

Give natural-language feedback and request a background revision:

```text
feedback JOB_ID REVISION
There is no role documentation. Keep the negation. “Until 27” refers to age, not 2027. Do not combine the two people's biographies.
```

Provide your complete edited recap directly (no model call for saving it):

```text
replace JOB_ID REVISION
Paste your complete reviewed recap here.
```

Confirm voice names for this meeting, after checking the transcript/audio:

```text
speakers JOB_ID REVISION
SPEAKER_00 = Confirmed name for this voice
SPEAKER_01 = Confirmed name for this voice
```

Correct the speaker of one specific displayed turn, without renaming the whole cluster:

```text
speaker JOB_ID REVISION S000012 = Confirmed name
```

Correct misheard words in a displayed turn:

```text
correct JOB_ID REVISION S000012
Paste the corrected wording of this turn here.
```

Voice/word corrections queue a new recap revision. Original audio and ASR are retained; corrected wording has no invented word timestamps.

Correct displayed meeting details (each saves a new draft revision):

```text
date JOB_ID REVISION YYYY-MM-DD
```

```text
title JOB_ID REVISION
Correct meeting title
```

```text
participants JOB_ID REVISION
Confirmed participant name, Another confirmed participant name
```

See recap differences:

```text
changes JOB_ID
```

If a background revision failed, retry its saved feedback/corrections:

```text
retry JOB_ID REVISION
```

When the current displayed revision is satisfactory, explicitly approve exactly that revision:

```text
approve JOB_ID REVISION
```

Ordinary “okay” messages, model-written approval statements and quoted commands do not approve anything. Any newer revision needs fresh approval. The last approved immutable version stays in the knowledge workflow until its approved replacement is ready.
