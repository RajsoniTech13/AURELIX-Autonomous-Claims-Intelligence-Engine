const decoder = new TextDecoder();
let buffer = "";
const inputString = 'data: {"stage": "image_validator", "status": "running"}\n\ndata: {"stage": "image_validator", "status": "complete", "timestamp": "2026-07-31T19:19:29.567712+00:00"}\n\n';
buffer += decoder.decode(new TextEncoder().encode(inputString), { stream: true });

const lines = buffer.split("\n\n");
buffer = lines.pop() || "";

for (const line of lines) {
  if (line.startsWith("data: ")) {
    const data = JSON.parse(line.slice(6));
    console.log("Parsed:", data);
  }
}
console.log("Remaining buffer:", buffer);
