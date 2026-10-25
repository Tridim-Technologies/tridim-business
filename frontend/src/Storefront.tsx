import { useEffect, useState } from 'react'
import './Storefront.css'

type PublicStorefront = {
  store: { slug: string; name: string; currency: string }
  products: { name: string; description: string; unit: string; price: string }[]
}

export default function Storefront({ slug }: { slug: string }) {
  const [catalog, setCatalog] = useState<PublicStorefront | null>(null)
  const [loading, setLoading] = useState(true)
  const [unavailable, setUnavailable] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetch(`/api/storefronts/${encodeURIComponent(slug)}/`, {
      credentials: 'omit',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error('This storefront is unavailable.')
        return response.json() as Promise<PublicStorefront>
      })
      .then(setCatalog)
      .catch((reason: Error) => {
        if (reason.name !== 'AbortError') setUnavailable(true)
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [slug])

  useEffect(() => {
    if (catalog?.store.name) document.title = `${catalog.store.name} · Catalog`
    return () => { document.title = 'Tridim Business Platform' }
  }, [catalog?.store.name])

  return <main className="storefront-page">
    <header className="storefront-header"><a href="/" aria-label="Tridim Business Platform home">Tridim Business Platform</a><span>Product catalog</span></header>
    {loading ? <p className="storefront-message" role="status">Loading catalog…</p> : unavailable || !catalog ? <section className="storefront-message" role="alert"><h1>Catalog unavailable</h1><p>This storefront may be unpublished or the address may be incorrect.</p></section> : <>
      <section className="storefront-hero"><p className="eyebrow">PRODUCT CATALOG</p><h1>{catalog.store.name}</h1><p>Browse products available from this business.</p></section>
      {catalog.products.length ? <section className="storefront-products" aria-label={`${catalog.store.name} products`}>
        {catalog.products.map((product, index) => <article className="storefront-product" key={`${product.name}-${index}`}>
          <div className="storefront-product-mark" aria-hidden="true">{product.name.slice(0, 1).toUpperCase()}</div>
          <div className="storefront-product-body"><h2>{product.name}</h2><p>{product.description}</p><span className="storefront-unit">Sold by {product.unit}</span></div>
          <strong className="storefront-price">{catalog.store.currency} {product.price}</strong>
        </article>)}
      </section> : <p className="storefront-message">This catalog has no published products yet.</p>}
      <footer className="storefront-footer">Prices are shown in {catalog.store.currency}. This catalog does not accept orders or payments.</footer>
    </>}
  </main>
}
