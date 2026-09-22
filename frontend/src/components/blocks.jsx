import { useEffect, useRef, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/kit/alert'
import { Badge } from '@/components/kit/badge'
import {
  Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle,
} from '@/components/kit/card'
import { cn } from '@/lib/utils'
import { C } from '@/lib/format'

/**
 * Relay's compositions on top of shadcn primitives.
 *
 * Status colour is carried by a small mark — a dot, an icon tile, a bar —
 * never by tinting a whole surface. Surfaces stay neutral; that restraint is
 * most of what makes a dashboard read as expensive rather than loud.
 */

const TONE = {
  crit: 'bg-crit/10 text-crit',
  hot: 'bg-hot/10 text-hot',
  warn: 'bg-warn/12 text-warn',
  ok: 'bg-ok/10 text-ok',
  ice: 'bg-ice/10 text-ice-ink',
  mute: 'bg-muted text-muted-foreground',
}

export function Dot({ tone = 'mute', pulse, className }) {
  return (
    <span className={cn('relative inline-flex size-1.5 shrink-0', className)}>
      {pulse ? (
        <span
          className="absolute inset-0 animate-ping rounded-full opacity-60 motion-reduce:hidden"
          style={{ background: C[tone] ?? tone }}
        />
      ) : null}
      <span className="relative size-1.5 rounded-full" style={{ background: C[tone] ?? tone }} />
    </span>
  )
}

/** A badge that carries status by its dot, on a neutral outline. */
export function StatusBadge({ tone = 'mute', pulse, children, className }) {
  return (
    <Badge variant="outline" className={cn('gap-1.5 font-normal text-muted-foreground', className)}>
      <Dot tone={tone} pulse={pulse} />
      {children}
    </Badge>
  )
}

/**
 * A banner, built on shadcn's Alert: neutral card surface, the status hue
 * confined to one icon tile, then title, explanation and an optional action.
 */
export function Notice({ tone = 'crit', icon: Glyph, title, children, action, className }) {
  return (
    <Alert className={cn('flex items-center gap-3.5 py-3 pl-3 pr-3 shadow-xs', className)}>
      {Glyph ? (
        <span className={cn('grid size-9 shrink-0 place-items-center rounded-lg', TONE[tone])}>
          <Glyph className="size-[18px]" strokeWidth={1.9} />
        </span>
      ) : null}
      <div className="min-w-0 flex-1">
        <AlertTitle className="line-clamp-none text-sm font-semibold text-foreground">{title}</AlertTitle>
        {children ? (
          <AlertDescription className="mt-0.5 block text-[13px] leading-snug">{children}</AlertDescription>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </Alert>
  )
}

/** One headline number, in the shadcn "section cards" shape. */
export function Kpi({ label, value, tone, badge, foot, sub, onClick }) {
  return (
    <Card
      className={cn('gap-3 py-5 shadow-xs', onClick && 'cursor-pointer transition-colors hover:bg-muted/60')}
      onClick={onClick}
    >
      <CardHeader className="px-5">
        <CardDescription className="text-[13px]">{label}</CardDescription>
        <CardTitle className="font-sans text-[32px] font-semibold tabular-nums tracking-[-0.04em] leading-none mt-1.5">
          {value}
        </CardTitle>
        {badge ? (
          <CardAction>
            <StatusBadge tone={tone}>{badge}</StatusBadge>
          </CardAction>
        ) : null}
      </CardHeader>
      {foot || sub ? (
        <CardFooter className="flex-col items-start gap-0.5 px-5 text-[13px]">
          {foot ? <div className="font-medium text-foreground">{foot}</div> : null}
          {sub ? <div className="text-muted-foreground">{sub}</div> : null}
        </CardFooter>
      ) : null}
    </Card>
  )
}

/**
 * A titled card: header with optional description and action, then content.
 * Content is a flex column that takes the card's spare height, so a card
 * stretched by its grid row gives the room to its chart or list instead of
 * leaving a gap under it.
 */
export function Panel({ title, description, action, footer, children, className, contentClassName }) {
  return (
    <Card className={cn('gap-5 py-5 shadow-xs', className)}>
      <CardHeader className="px-5">
        <CardTitle className="text-[15px] tracking-[-0.015em]">{title}</CardTitle>
        {description ? <CardDescription className="text-[13px]">{description}</CardDescription> : null}
        {action ? <CardAction>{action}</CardAction> : null}
      </CardHeader>
      <CardContent className={cn('flex flex-1 flex-col px-5', contentClassName)}>{children}</CardContent>
      {footer ? (
        <CardFooter className="border-t px-5 pt-4 text-[13px] text-muted-foreground [.border-t]:pt-4">
          {footer}
        </CardFooter>
      ) : null}
    </Card>
  )
}

/** Page header shared by every rebuilt screen. */
export function PageHead({ title, children, action }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="h1">{title}</h1>
        {children ? <p className="lead mt-1.5 max-w-[68ch]">{children}</p> : null}
      </div>
      {action ? <div className="flex gap-2">{action}</div> : null}
    </div>
  )
}

/**
 * How many rows of `rowHeight` fit in the element behind `ref`.
 *
 * The measured element must not size itself from its rows (give it flex-1 and
 * put the rows in an absolutely positioned child), or showing more rows would
 * grow it and the count would chase itself.
 */
export function useFit(rowHeight, min = 3) {
  const ref = useRef(null)
  const [n, setN] = useState(min)
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const ro = new ResizeObserver(([entry]) => {
      setN(Math.max(min, Math.floor(entry.contentRect.height / rowHeight)))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [rowHeight, min])
  return [ref, n]
}
