import { Badge, Button } from '@/shared/ui';
import { useState } from 'react';

import { CompanyPage } from '@/pages/company';
import { Dashboard } from '@/pages/dashboard';
export function Admin({
  companyId,
  ownerView,
}: {
  companyId?: number;
  ownerView: boolean;
}) {
  const [openId, setOpenId] = useState<number | null>(companyId ?? null);
  return (
    <div className="app wide">
      <header className="top">
        <Button
          type="button"
          variant="ghost"
          className="brand h-auto p-0 text-white hover:bg-transparent hover:text-white"
          onClick={() => !companyId && setOpenId(null)}
          style={{ cursor: companyId ? 'default' : 'pointer' }}
        >
          <span className="logo">AI</span> маркетолог{' '}
          <Badge variant="secondary">
            {companyId ? 'кабинет компании' : 'админ'}
          </Badge>
        </Button>
      </header>
      {openId === null ? (
        <Dashboard open={setOpenId} />
      ) : (
        <CompanyPage
          key={openId}
          id={openId}
          limitsEditable={ownerView}
          back={companyId ? undefined : () => setOpenId(null)}
        />
      )}
    </div>
  );
}
