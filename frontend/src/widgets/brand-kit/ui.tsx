import { ConfirmAction, Button, Card, Input, Textarea, Label, FormErrors } from "@/shared/ui";
import { useState } from 'react';
import { api, type Company, brandSchema } from '@/entities/marketing';
import { useLoad, useEditorForm } from '@/shared/lib';

const KINDS: [string, string, string][] = [
  ['logo_color', 'Логотип — основной цвет', 'для светлых фонов, PNG'],
  ['logo_white', 'Логотип — белый', 'для тёмных фонов, PNG'],
  ['logo_black', 'Логотип — чёрный', 'монохромная печать, PNG'],
  ['icon', 'Графический знак', 'без текстовой части, PNG'],
  ['pattern', 'Паттерны', 'фирменные узоры, PNG/JPG'],
  ['font_heading', 'Шрифт заголовков', 'TTF/OTF'],
  ['font_body', 'Шрифт основного текста', 'TTF/OTF'],
  ['example', 'Примеры оформления', 'образцы, PNG/JPG'],
];

export function BrandKit({
  company,
  saved,
}: {
  company: Company;
  saved: () => void;
}) {
  const id = company.id;
  const [assets, reload, loadError] = useLoad(() => api.assets(id), [id]);
  const form = useEditorForm(brandSchema, {
    brand_colors: company.brand_colors,
    brand_rules: company.brand_rules,
  });
  const { values: f } = form;
  const [msg, setMsg] = useState('');
  const [prev, setPrev] = useState<{ url: string; style: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const colors = f.brand_colors.match(/#[0-9a-fA-F]{6}/g) ?? [];

  const save = async (values: typeof f) => {
    try {
      await api.updateCompany(id, values);
      saved();
      setMsg('Сохранено');
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const upload = async (kind: string, file: File | undefined) => {
    if (!file) return;
    try {
      await api.uploadAsset(id, kind, file);
      setMsg('');
      reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const preview = async (style: 'dark' | 'light') => {
    setBusy(true);
    try {
      setPrev({
        url: (
          await api.preview(
            id,
            company.name,
            'Пробная карточка в фирменном стиле',
            style,
          )
        ).url,
        style,
      });
    } catch (e) {
      setMsg((e as Error).message);
    }
    setBusy(false);
  };

  return (
    <form onSubmit={form.handleSubmit(save)} className="contents">
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      <FormErrors errors={form.formState.errors} />
      <div className="split">
        <div>
          <Card className="card">
            <h3>Фирменные цвета</h3>
            <Label>
              HEX через запятую, основной первым
              <Input
                {...form.register('brand_colors')}
                aria-invalid={!!form.formState.errors.brand_colors}
                placeholder="#196C7F, #285055, #DDE1E1"
              />
            </Label>
            <div className="swatches">
              {colors.map((c) => (
                <span
                  key={c}
                  className="swatch"
                  style={{ background: c }}
                  title={c}
                />
              ))}
            </div>
          </Card>
          <Card className="card">
            <h3>Правила бренда</h3>
            <Label>
              Что можно и нельзя (агент соблюдает и проверяет каждый материал)
              <Textarea
                rows={10}
                {...form.register('brand_rules')}
                aria-invalid={!!form.formState.errors.brand_rules}
              />
            </Label>
            <div className="row">
              <Button
                variant="default"
                type="submit"
                disabled={form.formState.isSubmitting}
              >
                Сохранить
              </Button>
              <span className="muted">{msg}</span>
            </div>
          </Card>
          <Card className="card">
            <h3>Предпросмотр карточки</h3>
            <p className="muted">
              Так будет выглядеть изображение к посту: шрифты, цвета и логотип
              из бренд-кита.
            </p>
            <div className="row">
              <Button
                type="button"
                disabled={busy}
                onClick={() => preview('dark')}
              >
                Тёмная
              </Button>
              <Button
                type="button"
                disabled={busy}
                onClick={() => preview('light')}
              >
                Светлая
              </Button>
            </div>
            {prev && (
              <img className="previewImg" src={prev.url} alt="Предпросмотр" />
            )}
          </Card>
        </div>
        <div>
          {KINDS.map(([kind, title, hint]) => {
            const items = (assets ?? []).filter((a) => a.kind === kind);
            return (
              <Card className="card" key={kind}>
                <div className="cardHead">
                  <b>{title}</b>
                  <Label className="uploadBtn">
                    + Загрузить
                    <Input
                      type="file"
                      hidden
                      onChange={(e) => {
                        upload(kind, e.target.files?.[0]);
                        e.target.value = '';
                      }}
                    />
                  </Label>
                </div>
                <span className="muted">{hint}</span>
                <div className="thumbs">
                  {items.map((a) => (
                    <div className="thumb" key={a.id}>
                      {kind.startsWith('font') ? (
                        <span className="fontName">Aa</span>
                      ) : (
                        <img src={a.url} alt={a.filename} />
                      )}
                      <small>{a.filename}</small>
                      <ConfirmAction
                        label={`Удалить ${a.filename}`}
                        description={`Удалить файл бренд-кита «${a.filename}»?`}
                        onConfirm={async () => {
                          await api.deleteAsset(a.id);
                          reload();
                        }}
                      >
                        ×
                      </ConfirmAction>
                    </div>
                  ))}
                  {items.length === 0 && (
                    <span className="muted">не загружено</span>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      </div>
    </form>
  );
}
