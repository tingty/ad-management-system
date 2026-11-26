/**
 * V4.149 · 系统级 UI 组件规范（全模块通用）
 *
 * 目标：输入框、下拉、文本域、按钮与「创意工作台」保持一模一样的外观，
 * 同时把系统默认布局收敛为从上到下的单列结构，统一间距与高度。
 *
 * 约定：
 * 1. 所有新增/重构功能必须使用本文件的 Ui* 组件，不再手写 input/select/textarea/button 样式；
 * 2. 控件同时挂 cwb-* 与 ui-* 类名，外观直接复用创意工作台既有 CSS，避免两套样式漂移；
 * 3. 布局类 ui-page / ui-card / ui-form / ui-form-row 均为纵向单列，间距由 CSS 变量统一提供。
 */
import { forwardRef } from 'react'
import type {
  AnchorHTMLAttributes,
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'

function join(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ').trim()
}

type UiButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'secondary' | 'primary'
  active?: boolean
  block?: boolean
}

/** 按钮：secondary 与创意工作台 cwb-link-btn 同款，primary 与 cwb-start 同款。 */
export function UiButton({
  variant = 'secondary', active = false, block = false, className = '', type = 'button', ...rest
}: UiButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={join(
        'ui-btn',
        variant === 'primary' ? 'ui-btn-primary cwb-start' : 'cwb-link-btn',
        active && 'active',
        block && 'block',
        className,
      )}
    />
  )
}

/** 链接形态的次级按钮：与 UiButton secondary 同款。 */
export function UiLinkButton({
  className = '', block = false, ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & { block?: boolean }) {
  return <a {...rest} className={join('ui-btn cwb-link-btn', block && 'block', className)} />
}

/** 单行输入框：与创意工作台 cwb-input 同款，固定 40px 高。 */
export const UiInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function UiInput({ className = '', ...rest }, ref) {
    return <input {...rest} ref={ref} className={join('ui-input cwb-input', className)} />
  },
)

/** 下拉框：与创意工作台 cwb-select 同款，固定 40px 高。 */
export function UiSelect({ className = '', children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={join('ui-select cwb-select', className)}>
      {children}
    </select>
  )
}

/** 文本域：与创意工作台 cwb-supplement-input 同款。 */
export function UiTextarea({ className = '', ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...rest} className={join('ui-textarea cwb-supplement-input', className)} />
}

/** 表单行：标签在上、控件在下，纵向排列；与创意工作台控件外观一致但布局更紧凑。 */
export function UiFormRow({
  label, hint, children, htmlFor,
}: { label: ReactNode; hint?: ReactNode; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="ui-form-row">
      <label className="ui-field-label" htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && <div className="ui-field-hint">{hint}</div>}
    </div>
  )
}

/** 模块卡片：标题、说明、动作区均为纵向排列，避免左右平铺。 */
export function UiCard({
  title, subtitle, actions, children, className = '',
}: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={join('ui-card cwb-input-card', className)}>
      {(title || subtitle || actions) && (
        <div className="ui-card-head">
          {title && <h3 className="ui-card-title">{title}</h3>}
          {subtitle && <div className="ui-card-subtitle">{subtitle}</div>}
          {actions && <div className="ui-action-row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

/** 次级面板：用于脚本分段、脚本 detail、确认闸门等。 */
export function UiPanel({
  title, subtitle, actions, children, className = '',
}: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div className={join('ui-panel', className)}>
      {(title || subtitle || actions) && (
        <div className="ui-panel-head">
          {title && <div className="ui-panel-title">{title}</div>}
          {subtitle && <div className="ui-panel-subtitle">{subtitle}</div>}
          {actions && <div className="ui-action-row">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  )
}

/** 纵向操作区：按钮一列排布；inline 时改为自动换行横排，仅用于少量纯操作。 */
export function UiActionRow({
  children, inline = false, className = '',
}: { children: ReactNode; inline?: boolean; className?: string }) {
  return <div className={join('ui-action-row', inline && 'inline', className)}>{children}</div>
}

/** 纵向堆栈：系统默认间距。 */
export function UiStack({
  children, gap = 'normal', className = '',
}: { children: ReactNode; gap?: 'tight' | 'normal' | 'loose'; className?: string }) {
  return <div className={join('ui-stack', `gap-${gap}`, className)}>{children}</div>
}

/** 勾选项：复选框与文案同一行，整块作为独立表单行出现。 */
export function UiCheckRow({
  checked, onChange, children, disabled = false,
}: { checked: boolean; onChange: (checked: boolean) => void; children: ReactNode; disabled?: boolean }) {
  return (
    <label className="ui-check-row">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={e => onChange(e.target.checked)} />
      <span>{children}</span>
    </label>
  )
}
