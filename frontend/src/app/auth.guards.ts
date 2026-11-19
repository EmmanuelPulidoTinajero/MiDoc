import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { ApiService } from './api.service';

export const authGuard: CanActivateFn = (_route, state) => {
  const api = inject(ApiService);
  const router = inject(Router);
  if (api.user()) return true;
  return router.createUrlTree(['/acceso'], {
    queryParams: { returnUrl: state.url },
  });
};

export const patientGuard: CanActivateFn = (_route, state) => {
  const api = inject(ApiService);
  const router = inject(Router);
  if (api.isPatient()) return true;
  if (api.isDoctor()) return router.createUrlTree(['/panel']);
  return router.createUrlTree(['/acceso'], {
    queryParams: { returnUrl: state.url },
  });
};

export const doctorGuard: CanActivateFn = (_route, state) => {
  const api = inject(ApiService);
  const router = inject(Router);
  if (api.isDoctor()) return true;
  if (api.isPatient()) return router.createUrlTree(['/buscar']);
  return router.createUrlTree(['/acceso'], {
    queryParams: { returnUrl: state.url },
  });
};

export const guestGuard: CanActivateFn = () => {
  const api = inject(ApiService);
  const router = inject(Router);
  if (!api.user()) return true;
  return router.createUrlTree([api.isDoctor() ? '/panel' : '/buscar']);
};
