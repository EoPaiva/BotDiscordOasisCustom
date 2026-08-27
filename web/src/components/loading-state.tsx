export function LoadingState({ label = "Carregando dados operacionais" }: { label?: string }) {
  return (
    <div aria-busy="true" aria-label={label} aria-live="polite" className="loading-stack" role="status">
      <span className="visually-hidden">{label}</span>
      <div aria-hidden="true" className="skeleton title" />
      <div aria-hidden="true" className="skeleton strip" />
      <div aria-hidden="true" className="skeleton body" />
    </div>
  );
}
