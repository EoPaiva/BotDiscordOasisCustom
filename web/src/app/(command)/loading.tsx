export default function Loading() {
  return (
    <div className="loading-stack" aria-label="Carregando dados operacionais" aria-live="polite">
      <div className="skeleton title" />
      <div className="skeleton strip" />
      <div className="skeleton body" />
    </div>
  );
}
