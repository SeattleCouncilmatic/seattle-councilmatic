import { useEffect } from 'react'

const SITE_NAME = 'Seattle Councilmatic'

// Sets <title> to "<pageTitle> — Seattle Councilmatic" on mount /
// when pageTitle changes; falls back to just "Seattle Councilmatic"
// when pageTitle is empty/undefined (so a detail page in its loading
// state doesn't leak the previous page's title — pass `null` until
// the data resolves).
//
// WCAG 2.4.2 (Page Titled). Pair with a single <h1> per page so the
// browser tab, bookmark, and screen-reader page announcement all
// align.
export default function useDocumentTitle(pageTitle) {
  useEffect(() => {
    document.title = pageTitle
      ? `${pageTitle} — ${SITE_NAME}`
      : SITE_NAME
  }, [pageTitle])
}
