import type { Block, Inline } from "@/lib/markdown";

function Text({ parts }: { parts: Inline[] }) {
  return parts.map((part, index) =>
    part.kind === "strong" ? (
      <strong key={index}>{part.text}</strong>
    ) : part.kind === "link" ? (
      <a
        key={index}
        href={part.href}
        {...(part.href.startsWith("https://")
          ? { rel: "noopener", target: "_blank" }
          : {})}
      >
        {part.text}
      </a>
    ) : (
      part.text
    ),
  );
}

export default function Markdown({ blocks }: { blocks: Block[] }) {
  return blocks.map((block, index) => {
    switch (block.kind) {
      case "h2":
        return (
          <h2 key={index} id={block.id}>
            {block.text}
          </h2>
        );
      case "h3":
        return (
          <h3 key={index} id={block.id}>
            {block.text}
          </h3>
        );
      case "quote":
        return (
          <blockquote key={index}>
            <p>
              <Text parts={block.inline} />
            </p>
          </blockquote>
        );
      case "ul":
      case "ol": {
        const List = block.kind;
        return (
          <List key={index}>
            {block.items.map((item, i) => (
              <li key={i}>
                <Text parts={item} />
              </li>
            ))}
          </List>
        );
      }
      default:
        return (
          <p key={index}>
            <Text parts={block.inline} />
          </p>
        );
    }
  });
}
