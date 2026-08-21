FROM node:20-alpine

# Minimal sandbox image for Node.js target code execution.
# Security: no shell, no package manager network access after build.
# Target code is copied read-only; tmpfs for /tmp only.

RUN addgroup -S sandbox && adduser -S sandbox -G sandbox

WORKDIR /app
RUN chown sandbox:sandbox /app

USER sandbox

# CMD is overridden by the sandbox runner per-execution
CMD ["node", "--version"]
