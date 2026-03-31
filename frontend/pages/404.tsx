export default function NotFoundPage() {
  return (
    <div
      style={{
        display: "flex",
        minHeight: "100vh",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <h1 style={{ fontSize: "2rem", fontWeight: "bold" }}>404</h1>
        <p style={{ marginTop: "0.5rem", color: "#71717a" }}>Page not found</p>
      </div>
    </div>
  );
}
