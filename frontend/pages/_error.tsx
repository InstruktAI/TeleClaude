function Error({ statusCode }: { statusCode?: number }) {
  return (
    <div style={{ display: "flex", minHeight: "100vh", alignItems: "center", justifyContent: "center" }}>
      <div style={{ textAlign: "center" }}>
        <h1 style={{ fontSize: "2rem", fontWeight: "bold" }}>{statusCode ?? "Error"}</h1>
        <p style={{ marginTop: "0.5rem", color: "#71717a" }}>
          {statusCode === 404 ? "Page not found" : "An error occurred"}
        </p>
      </div>
    </div>
  );
}

Error.getInitialProps = ({ res, err }: { res?: { statusCode: number }; err?: { statusCode: number } }) => {
  const statusCode = res ? res.statusCode : err ? err.statusCode : 404;
  return { statusCode };
};

export default Error;
