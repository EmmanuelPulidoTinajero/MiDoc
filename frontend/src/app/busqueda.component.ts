import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
  ApiService,
  DAYS,
  Doctor,
  createIdempotencyKey,
  errorMessage,
  formatDateTime,
  formatTime,
  todayInMexico,
} from './api.service';
import {
  DsAlertBannerComponent,
  DsBadgeComponent,
  DsButtonComponent,
  DsCardComponent,
  DsControlDirective,
  DsEmptyStateComponent,
  DsFieldComponent,
  DsPageHeaderComponent,
  DsSkeletonComponent,
} from './ds';

export type DoctorSortOption = 'NAME' | 'PRICE_ASC' | 'PRICE_DESC' | 'AVAILABILITY';

/** Flujo 1: buscar profesionales, ver perfil y horarios libres, y confirmar cita. */
@Component({
  selector: 'midoc-busqueda',
  standalone: true,
  imports: [
    FormsModule,
    DsAlertBannerComponent,
    DsBadgeComponent,
    DsButtonComponent,
    DsCardComponent,
    DsControlDirective,
    DsEmptyStateComponent,
    DsFieldComponent,
    DsPageHeaderComponent,
    DsSkeletonComponent,
  ],
  templateUrl: './busqueda.component.html',
})
export class BusquedaComponent implements OnInit {
  readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  specialty = '';
  location = '';
  text = '';
  sort: DoctorSortOption = 'NAME';

  readonly doctors = signal<Doctor[]>([]);
  readonly searching = signal(false);
  readonly searched = signal(false);
  readonly searchError = signal('');
  readonly booking = signal(false);
  readonly openingDoctorId = signal<string | null>(null);
  readonly loadingSlots = signal(false);
  readonly updatingConsent = signal(false);
  readonly message = signal('');

  readonly selected = signal<Doctor | null>(null);
  date = todayInMexico(1);
  readonly slots = signal<string[]>([]);
  readonly selectedSlot = signal<string | null>(null);
  readonly slotsMessage = signal('');
  reason = '';
  readonly bookingMessage = signal('');
  readonly bookingSuccess = signal(false);
  readonly consentMessage = signal('');

  readonly minDate = todayInMexico();
  readonly maxDate = todayInMexico(90);
  readonly days = DAYS;
  readonly formatTime = formatTime;
  readonly formatDateTime = formatDateTime;

  ngOnInit(): void {
    void this.search();
    const doctorId = this.route.snapshot.paramMap.get('id');
    if (doctorId) {
      // Deep link: /doctores/:id abre el perfil directamente (L7).
      void this.openById(doctorId);
    }
  }

  hasActiveFilters(): boolean {
    return !!(
      this.specialty.trim() ||
      this.location.trim() ||
      this.text.trim() ||
      this.sort !== 'NAME'
    );
  }

  clearFilters(): void {
    this.specialty = '';
    this.location = '';
    this.text = '';
    this.sort = 'NAME';
    void this.search();
  }

  discountPercent(doctor: Doctor): number {
    if (doctor.promotionSummary && doctor.promotionSummary.maxDiscountPercent > 0) {
      return doctor.promotionSummary.maxDiscountPercent;
    }
    const promos = doctor.promotions ?? [];
    if (!promos.length) return 0;
    return Math.max(...promos.map((p) => p.discountPercent));
  }

  effectivePrice(doctor: Doctor): number {
    if (doctor.promotionSummary) {
      return doctor.promotionSummary.discountedPrice;
    }
    const pct = this.discountPercent(doctor);
    if (pct <= 0) return doctor.price;
    return Math.round(doctor.price * (1 - pct / 100) * 100) / 100;
  }

  async search(): Promise<void> {
    const params: Record<string, string> = {};
    if (this.specialty.trim()) params['specialty'] = this.specialty.trim();
    if (this.location.trim()) params['location'] = this.location.trim();
    if (this.text.trim()) params['q'] = this.text.trim();
    if (this.sort !== 'NAME') params['sort'] = this.sort;

    this.searching.set(true);
    this.searched.set(true);
    this.searchError.set('');
    try {
      const result = await this.api.get<Doctor[]>('/api/doctors', params);
      this.doctors.set(result);
      this.message.set(`${result.length} profesional(es) encontrado(s).`);
    } catch (error) {
      const err = errorMessage(error);
      this.searchError.set(err);
      this.message.set('');
    } finally {
      this.searching.set(false);
    }
  }

  async open(doctor: Doctor): Promise<void> {
    this.bookingMessage.set('');
    this.bookingSuccess.set(false);
    this.consentMessage.set('');
    this.selectedSlot.set(null);
    await this.openById(doctor.id);
    if (this.selected()) {
      await this.router.navigate(['/doctores', doctor.id]);
    }
  }

  async openById(doctorId: string): Promise<void> {
    this.openingDoctorId.set(doctorId);
    try {
      const detail = await this.api.get<Doctor>(`/api/doctors/${doctorId}`);
      this.selected.set(detail);
      await this.loadSlots();
    } catch (error) {
      this.searchError.set(errorMessage(error));
    } finally {
      this.openingDoctorId.set(null);
    }
  }

  closeProfile(): void {
    this.selected.set(null);
    this.selectedSlot.set(null);
    if (this.route.snapshot.paramMap.get('id')) {
      void this.router.navigate(['/buscar']);
    }
  }

  async loadSlots(): Promise<void> {
    const doctor = this.selected();
    if (!doctor) return;
    this.selectedSlot.set(null);
    this.loadingSlots.set(true);
    this.slotsMessage.set('');
    try {
      const result = await this.api.get<{ slots: string[] }>(`/api/doctors/${doctor.id}/availability`, {
        date: this.date,
      });
      this.slots.set(result.slots);
      this.slotsMessage.set(
        result.slots.length ? '' : 'No hay horarios disponibles ese día. Prueba otra fecha.',
      );
    } catch (error) {
      this.slots.set([]);
      this.slotsMessage.set(errorMessage(error));
    } finally {
      this.loadingSlots.set(false);
    }
  }

  selectSlot(slot: string): void {
    this.bookingMessage.set('');
    this.bookingSuccess.set(false);
    this.selectedSlot.set(slot);
  }

  async confirmBooking(): Promise<void> {
    const slot = this.selectedSlot();
    const doctor = this.selected();
    if (!slot || !doctor || this.booking()) return;
    if (!this.api.user()) {
      await this.goToLogin();
      return;
    }
    if (!this.api.isPatient()) {
      this.bookingSuccess.set(false);
      this.bookingMessage.set(
        'Iniciaste sesión como profesional. Para agendar una cita, accede con una cuenta de paciente.',
      );
      return;
    }
    this.booking.set(true);
    this.bookingMessage.set('');
    try {
      await this.api.post(
        '/api/appointments',
        { doctorId: doctor.id, dateTime: slot, reason: this.reason.trim() || undefined },
        { 'Idempotency-Key': createIdempotencyKey() },
      );
      this.bookingSuccess.set(true);
      this.bookingMessage.set(
        `Cita confirmada con ${doctor.name} el ${formatDateTime(slot)}.`,
      );
      this.reason = '';
      this.selectedSlot.set(null);
      await this.loadSlots();
    } catch (error) {
      this.bookingSuccess.set(false);
      this.bookingMessage.set(errorMessage(error));
      await this.loadSlots();
    } finally {
      this.booking.set(false);
    }
  }

  async grantAccess(): Promise<void> {
    const doctor = this.selected();
    if (!doctor || this.updatingConsent()) return;
    this.updatingConsent.set(true);
    try {
      await this.api.post('/api/consents', { doctorId: doctor.id, granted: true });
      this.consentMessage.set(
        `${doctor.name} ya tiene permiso para consultar tu expediente. Puedes revocarlo en Mi expediente.`,
      );
    } catch (error) {
      this.consentMessage.set(errorMessage(error));
    } finally {
      this.updatingConsent.set(false);
    }
  }

  goToLogin(): Promise<boolean> {
    return this.router.navigate(['/acceso'], { queryParams: { returnUrl: '/buscar' } });
  }

  goToAppointments(): Promise<boolean> {
    return this.router.navigate(['/citas']);
  }
}
