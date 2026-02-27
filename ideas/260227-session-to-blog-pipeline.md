# Session-to-Blog Pipeline

Deep AI conversations naturally produce insights worth sharing. The platform should
facilitate the exhale from session to published narrative automatically.

## The flow

1. A deep conversation happens (like the agent shorthand design session).
2. At the end, the human or AI triggers a "publish" step.
3. The session transcript is distilled into a storytelling blog post — not a raw
   transcript, but a narrative that captures what was explored, what was discovered,
   and why it matters.
4. The post is published to the blog with minimal friction.

## Dependencies

- Public website with blog section (todo: public-website-blog).
- Blog content format and publication workflow.
- A skill or command that takes a session ID and produces a draft post.

## Open questions

- How much human editing is expected before publication?
- Should the AI propose the post and the human approve, or vice versa?
- What metadata should be captured (session IDs, participants, topics)?
