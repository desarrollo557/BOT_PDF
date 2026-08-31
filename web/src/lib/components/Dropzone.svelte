<script lang="ts">
  interface Props {
    onfiles: (files: File[]) => void;
    disabled?: boolean;
  }

  let { onfiles, disabled = false }: Props = $props();

  let hovering = $state(false);
  let rejected = $state(0);
  let input: HTMLInputElement;

  function accept(list: FileList | null) {
    if (!list || disabled) return;
    const all = Array.from(list);
    const pdfs = all.filter((file) => file.name.toLowerCase().endsWith('.pdf'));
    // Say what was dropped and ignored. Silently discarding files is how an
    // operator ends up believing a document was processed when it never was.
    rejected = all.length - pdfs.length;
    if (pdfs.length) onfiles(pdfs);
  }
</script>

<div
  class="flex flex-col items-center justify-center gap-1 rounded-xl border border-dashed p-11
         transition-colors {disabled
    ? 'cursor-not-allowed border-hairline bg-surface opacity-55'
    : 'cursor-pointer bg-surface hover:bg-plane'} {hovering ? 'border-s1 bg-plane' : 'border-axis'}"
  role="button"
  tabindex="0"
  ondragover={(event) => {
    event.preventDefault();
    hovering = true;
  }}
  ondragleave={() => (hovering = false)}
  ondrop={(event) => {
    event.preventDefault();
    hovering = false;
    accept(event.dataTransfer?.files ?? null);
  }}
  onclick={() => !disabled && input.click()}
  onkeydown={(event) => {
    if (event.key === 'Enter' || event.key === ' ') input.click();
  }}
>
  <strong class="font-semibold">Arrastre los PDF aquí</strong>
  <span class="text-sm text-muted">
    o haga clic para seleccionarlos — puede cargar 50 o más de una vez
  </span>
  {#if rejected}
    <span class="mt-1 text-sm text-warning">
      Se ignoraron {rejected} archivo{rejected === 1 ? '' : 's'} que no son PDF
    </span>
  {/if}
  <input
    bind:this={input}
    type="file"
    accept="application/pdf"
    multiple
    hidden
    onchange={(event) => {
      accept(event.currentTarget.files);
      event.currentTarget.value = '';
    }}
  />
</div>
