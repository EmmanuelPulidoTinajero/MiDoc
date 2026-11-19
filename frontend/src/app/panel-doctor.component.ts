import { Component, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
  ApiService,
  DAYS,
  InventoryItem,
  MedicalDocument,
  MedicalRecord,
  Patient,
  PaymentMode,
  Profile,
  Promotion,
  Subscription,
  errorMessage,
  formatDateTime,
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
  DsModalComponent,
  DsPageHeaderComponent,
  DsSkeletonComponent,
} from './ds';
import { ExpedienteVistaComponent } from './expediente-vista.component';

interface BlockForm {
  day: number;
  start: string;
  end: string;
}

/** Flujo 3: suscripción Stripe ($20 USD/mes), perfil, horario, inventario, promociones y pacientes. */
@Component({
  selector: 'midoc-panel-doctor',
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
    DsModalComponent,
    DsPageHeaderComponent,
    DsSkeletonComponent,
    ExpedienteVistaComponent,
  ],
  templateUrl: './panel-doctor.component.html',
})
export class PanelDoctorComponent implements OnInit {
  readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly subscription = signal<Subscription | null>(null);
  readonly subscriptionHistory = signal<Subscription[]>([]);
  readonly paymentMode = signal<PaymentMode>(this.api.paymentMode());
  readonly loading = signal(true);
  readonly loadFailed = signal(false);

  readonly patients = signal<Patient[]>([]);
  readonly selectedPatientId = signal<string | null>(null);
  readonly loadingRecord = signal(false);
  readonly patientRecord = signal<MedicalRecord | null>(null);
  readonly patientDocuments = signal<MedicalDocument[]>([]);

  readonly inventory = signal<InventoryItem[]>([]);
  readonly promotions = signal<Promotion[]>([]);

  readonly paying = signal(false);
  readonly confirmingStripe = signal(false);
  readonly savingProfile = signal(false);
  readonly savingSchedule = signal(false);
  readonly savingInventory = signal(false);
  readonly savingPromotion = signal(false);
  readonly deletingInventory = signal(false);
  readonly deletingPromotion = signal(false);

  readonly subscriptionMessage = signal('');
  readonly subscriptionTone = signal<'info' | 'success' | 'warning' | 'danger'>('info');
  readonly profileMessage = signal('');
  readonly profileTone = signal<'success' | 'danger'>('success');
  readonly scheduleMessage = signal('');
  readonly scheduleTone = signal<'success' | 'danger'>('success');
  readonly inventoryMessage = signal('');
  readonly inventoryTone = signal<'success' | 'danger'>('success');
  readonly promotionMessage = signal('');
  readonly promotionTone = signal<'success' | 'danger'>('success');
  readonly patientsMessage = signal('');

  readonly pendingDeleteInventory = signal<InventoryItem | null>(null);
  readonly pendingDeletePromotion = signal<Promotion | null>(null);
  readonly editingInventoryId = signal<string | null>(null);
  readonly editingPromotionId = signal<string | null>(null);

  readonly days = DAYS.map((name, value) => ({ name, value })).slice(1);
  readonly formatDateTime = formatDateTime;

  profileForm = {
    nombreCompleto: '',
    telefono: '',
    especialidad: '',
    ubicacion: '',
    ciudad: '',
    precioConsulta: 500,
    duracionCitaMin: 30,
    biografia: '',
    currentPassword: '',
    newPassword: '',
  };

  inventoryForm = { name: '', quantity: 0, unit: 'piezas' };
  editInventoryForm = { name: '', quantity: 0, unit: 'piezas' };

  promotionForm = {
    title: '',
    description: '',
    discountPercent: 10,
    start: todayInMexico(),
    end: todayInMexico(30),
  };
  editPromotionForm = {
    title: '',
    description: '',
    discountPercent: 10,
    start: todayInMexico(),
    end: todayInMexico(30),
  };

  blocks: BlockForm[] = [];

  private handledStripeSessionId: string | null = null;

  constructor() {
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      const status = params.get('stripe_status');
      const sessionId = params.get('session_id');
      if (status === 'success' && sessionId && sessionId !== this.handledStripeSessionId) {
        this.handledStripeSessionId = sessionId;
        void this.confirmStripeReturn(sessionId);
      } else if (status === 'cancel') {
        this.subscriptionTone.set('warning');
        this.subscriptionMessage.set(
          'El pago fue cancelado en Stripe. Puedes intentarlo nuevamente cuando estés listo.',
        );
        void this.clearStripeQueryParams();
      }
    });
  }

  ngOnInit(): void {
    void this.load();
  }

  subscriptionStatusKey(): string {
    const sub = this.subscription();
    if (!sub) return 'SIN_SUSCRIPCION';
    if (sub.active) return 'ACTIVA';
    if (sub.status === 'PENDIENTE') return 'PENDIENTE';
    return 'INACTIVA';
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.loadFailed.set(false);
    try {
      const [me, overview] = await Promise.all([
        this.api.get<Profile>('/api/me'),
        this.api.getSubscriptions().catch(() => null),
      ]);

      this.subscription.set(overview?.subscription ?? me.subscription ?? null);
      this.subscriptionHistory.set(overview?.history ?? []);
      this.paymentMode.set(overview?.paymentMode ?? this.api.paymentMode());

      const doctor = me.doctor;
      if (doctor) {
        this.blocks = (doctor.schedule ?? []).map((b) => ({
          day: b.dia_semana,
          start: b.hora_inicio,
          end: b.hora_fin,
        }));
        this.profileForm = {
          nombreCompleto: doctor.name ?? me.name ?? '',
          telefono: me.phone ?? '',
          especialidad: doctor.specialty ?? '',
          ubicacion: doctor.location ?? '',
          ciudad: doctor.city ?? '',
          precioConsulta: doctor.price ?? 500,
          duracionCitaMin: doctor.durationMin ?? 30,
          biografia: doctor.description ?? '',
          currentPassword: '',
          newPassword: '',
        };
      }

      await this.loadPatients();
      if (this.subscription()?.active) {
        await this.loadBusinessLists();
      }
    } catch (error) {
      this.loadFailed.set(true);
      this.subscriptionTone.set('danger');
      this.subscriptionMessage.set(errorMessage(error));
    } finally {
      this.loading.set(false);
    }
  }

  private buildStripeReturnUrls(): { successUrl: string; cancelUrl: string } {
    const origin = globalThis.location.origin;
    const rawPath = globalThis.location.pathname || '/';
    const base = `${origin}${rawPath}`;
    return {
      successUrl: `${base}#/panel/suscripcion?stripe_status=success&session_id={CHECKOUT_SESSION_ID}`,
      cancelUrl: `${base}#/panel/suscripcion?stripe_status=cancel`,
    };
  }

  navigateExternal(url: string): void {
    globalThis.location.assign(url);
  }

  async startStripeCheckout(): Promise<void> {
    if (this.paying() || this.confirmingStripe()) return;
    this.paying.set(true);
    this.subscriptionMessage.set('');
    try {
      const urls = this.buildStripeReturnUrls();
      const checkout = await this.api.createSubscriptionCheckout(urls);
      this.paymentMode.set(checkout.mode);
      if (checkout.mode === 'simulado') {
        // Modo simulado: no hay salida a Stripe; se confirma la sesión propia al instante.
        const end = await this.confirmStripeReturn(checkout.sessionId);
        this.subscriptionTone.set('success');
        this.subscriptionMessage.set(
          `Pago simulado (sin cargo real): suscripción activa. Vigente hasta el ${end ?? '—'}`.trim(),
        );
        this.paying.set(false);
        return;
      }
      this.navigateExternal(checkout.checkoutUrl);
    } catch (error) {
      this.subscriptionTone.set('danger');
      this.subscriptionMessage.set(errorMessage(error));
      this.paying.set(false);
    }
  }

  private async confirmStripeReturn(sessionId: string): Promise<string | null> {
    this.confirmingStripe.set(true);
    try {
      const result = await this.api.confirmSubscription(sessionId);
      const cardInfo = result.payment.cardLast4
        ? ` con ${result.payment.cardBrand || 'tarjeta'} terminación ${result.payment.cardLast4}`
        : '';
      this.subscriptionTone.set('success');
      this.subscriptionMessage.set(
        `Suscripción confirmada${cardInfo}. Vigente hasta el ${result.subscription.end ?? ''}.`,
      );
      await this.clearStripeQueryParams();
      await this.load();
      return result.subscription.end ?? null;
    } catch (error) {
      this.subscriptionTone.set('danger');
      this.subscriptionMessage.set(errorMessage(error));
      await this.clearStripeQueryParams();
      return null;
    } finally {
      this.confirmingStripe.set(false);
    }
  }

  private clearStripeQueryParams(): Promise<boolean> {
    return this.router.navigate(['/panel/suscripcion'], { replaceUrl: true });
  }

  async saveProfile(): Promise<void> {
    if (this.savingProfile()) return;
    if (
      (this.profileForm.currentPassword && !this.profileForm.newPassword) ||
      (!this.profileForm.currentPassword && this.profileForm.newPassword)
    ) {
      this.profileTone.set('danger');
      this.profileMessage.set('Para cambiar tu contraseña, completa la contraseña actual y la nueva.');
      return;
    }

    this.savingProfile.set(true);
    this.profileMessage.set('');
    try {
      const payload: Record<string, unknown> = {
        nombreCompleto: this.profileForm.nombreCompleto.trim(),
        telefono: this.profileForm.telefono.trim() || null,
        especialidad: this.profileForm.especialidad.trim(),
        ubicacion: this.profileForm.ubicacion.trim(),
        ciudad: this.profileForm.ciudad.trim() || null,
        precioConsulta: Number(this.profileForm.precioConsulta),
        duracionCitaMin: Number(this.profileForm.duracionCitaMin),
        biografia: this.profileForm.biografia.trim() || null,
      };
      if (this.profileForm.currentPassword && this.profileForm.newPassword) {
        payload['currentPassword'] = this.profileForm.currentPassword;
        payload['newPassword'] = this.profileForm.newPassword;
      }
      await this.api.updateMe(payload);
      this.profileForm.currentPassword = '';
      this.profileForm.newPassword = '';
      this.profileTone.set('success');
      this.profileMessage.set('Perfil profesional actualizado.');
    } catch (error) {
      this.profileTone.set('danger');
      this.profileMessage.set(errorMessage(error));
    } finally {
      this.savingProfile.set(false);
    }
  }

  async loadBusinessLists(): Promise<void> {
    try {
      const [inventory, promotions] = await Promise.all([
        this.api.get<InventoryItem[]>('/api/doctor/inventory'),
        this.api.get<Promotion[]>('/api/doctor/promotions'),
      ]);
      this.inventory.set(inventory);
      this.promotions.set(promotions);
    } catch (error) {
      this.inventoryTone.set('danger');
      this.inventoryMessage.set(errorMessage(error));
    }
  }

  async saveInventoryItem(): Promise<void> {
    if (this.savingInventory()) return;
    this.savingInventory.set(true);
    try {
      await this.api.post('/api/doctor/inventory', {
        name: this.inventoryForm.name.trim(),
        quantity: Number(this.inventoryForm.quantity),
        unit: this.inventoryForm.unit.trim(),
      });
      this.inventoryForm = { ...this.inventoryForm, name: '', quantity: 0 };
      this.inventoryTone.set('success');
      this.inventoryMessage.set('Inventario actualizado.');
      await this.loadBusinessLists();
    } catch (error) {
      this.inventoryTone.set('danger');
      this.inventoryMessage.set(errorMessage(error));
    } finally {
      this.savingInventory.set(false);
    }
  }

  startEditInventory(item: InventoryItem): void {
    this.editingInventoryId.set(item.id);
    this.editInventoryForm = { name: item.name, quantity: item.quantity, unit: item.unit };
  }

  async saveEditInventory(): Promise<void> {
    if (!this.editingInventoryId() || this.savingInventory()) return;
    this.savingInventory.set(true);
    try {
      await this.api.post('/api/doctor/inventory', {
        name: this.editInventoryForm.name.trim(),
        quantity: Number(this.editInventoryForm.quantity),
        unit: this.editInventoryForm.unit.trim(),
      });
      this.editingInventoryId.set(null);
      this.inventoryTone.set('success');
      this.inventoryMessage.set('Existencias actualizadas.');
      await this.loadBusinessLists();
    } catch (error) {
      this.inventoryTone.set('danger');
      this.inventoryMessage.set(errorMessage(error));
    } finally {
      this.savingInventory.set(false);
    }
  }

  async confirmDeleteInventory(): Promise<void> {
    const item = this.pendingDeleteInventory();
    if (!item || this.deletingInventory()) return;
    this.deletingInventory.set(true);
    try {
      await this.api.delete(`/api/doctor/inventory/${item.id}`);
      this.inventory.update((items) => items.filter((value) => value.id !== item.id));
      this.pendingDeleteInventory.set(null);
      this.inventoryTone.set('success');
      this.inventoryMessage.set(`Insumo «${item.name}» eliminado.`);
    } catch (error) {
      this.pendingDeleteInventory.set(null);
      this.inventoryTone.set('danger');
      this.inventoryMessage.set(errorMessage(error));
    } finally {
      this.deletingInventory.set(false);
    }
  }

  async savePromotion(): Promise<void> {
    if (this.savingPromotion()) return;
    if (this.promotionForm.end < this.promotionForm.start) {
      this.promotionTone.set('danger');
      this.promotionMessage.set('La fecha de término debe ser igual o posterior a la fecha de inicio.');
      return;
    }
    this.savingPromotion.set(true);
    try {
      await this.api.post('/api/doctor/promotions', {
        ...this.promotionForm,
        title: this.promotionForm.title.trim(),
        description: this.promotionForm.description.trim(),
        discountPercent: Number(this.promotionForm.discountPercent),
      });
      this.promotionForm = { ...this.promotionForm, title: '', description: '' };
      this.promotionTone.set('success');
      this.promotionMessage.set('Promoción publicada en el directorio.');
      await this.loadBusinessLists();
    } catch (error) {
      this.promotionTone.set('danger');
      this.promotionMessage.set(errorMessage(error));
    } finally {
      this.savingPromotion.set(false);
    }
  }

  startEditPromotion(promotion: Promotion): void {
    this.editingPromotionId.set(promotion.id);
    this.editPromotionForm = {
      title: promotion.title,
      description: promotion.description,
      discountPercent: promotion.discountPercent,
      start: promotion.start,
      end: promotion.end,
    };
  }

  async saveEditPromotion(): Promise<void> {
    const oldId = this.editingPromotionId();
    if (!oldId || this.savingPromotion()) return;
    if (this.editPromotionForm.end < this.editPromotionForm.start) {
      this.promotionTone.set('danger');
      this.promotionMessage.set('La fecha de término debe ser igual o posterior a la fecha de inicio.');
      return;
    }
    this.savingPromotion.set(true);
    try {
      // Crear primero el reemplazo y retirar el anterior sólo si el POST tuvo éxito.
      await this.api.post('/api/doctor/promotions', {
        ...this.editPromotionForm,
        title: this.editPromotionForm.title.trim(),
        description: this.editPromotionForm.description.trim(),
        discountPercent: Number(this.editPromotionForm.discountPercent),
      });
      await this.api.delete(`/api/doctor/promotions/${oldId}`);
      this.editingPromotionId.set(null);
      this.promotionTone.set('success');
      this.promotionMessage.set('Promoción actualizada en el directorio.');
      await this.loadBusinessLists();
    } catch (error) {
      this.promotionTone.set('danger');
      this.promotionMessage.set(errorMessage(error));
    } finally {
      this.savingPromotion.set(false);
    }
  }

  async confirmDeletePromotion(): Promise<void> {
    const promotion = this.pendingDeletePromotion();
    if (!promotion || this.deletingPromotion()) return;
    this.deletingPromotion.set(true);
    try {
      await this.api.delete(`/api/doctor/promotions/${promotion.id}`);
      this.promotions.update((items) => items.filter((value) => value.id !== promotion.id));
      this.pendingDeletePromotion.set(null);
      this.promotionTone.set('success');
      this.promotionMessage.set(`Promoción «${promotion.title}» retirada.`);
    } catch (error) {
      this.pendingDeletePromotion.set(null);
      this.promotionTone.set('danger');
      this.promotionMessage.set(errorMessage(error));
    } finally {
      this.deletingPromotion.set(false);
    }
  }

  async loadPatients(): Promise<void> {
    if (!this.subscription()?.active) {
      this.patients.set([]);
      this.patientsMessage.set('Activa tu suscripción para consultar los expedientes de tus pacientes autorizados.');
      return;
    }
    try {
      this.patients.set(await this.api.get<Patient[]>('/api/doctor/patients'));
      this.patientsMessage.set('');
    } catch (error) {
      this.patientsMessage.set(errorMessage(error));
    }
  }

  addBlock(): void {
    this.blocks = [...this.blocks, { day: 1, start: '09:00', end: '14:00' }];
  }

  removeBlock(index: number): void {
    this.blocks = this.blocks.filter((_, i) => i !== index);
  }

  async saveSchedule(): Promise<void> {
    if (this.savingSchedule()) return;
    for (const block of this.blocks) {
      if (block.end <= block.start) {
        this.scheduleTone.set('danger');
        this.scheduleMessage.set('Cada bloque debe tener una hora de fin posterior a la hora de inicio.');
        return;
      }
    }
    this.savingSchedule.set(true);
    try {
      await this.api.put('/api/doctor/schedule', {
        blocks: this.blocks.map((b) => ({ ...b, day: Number(b.day) })),
      });
      this.scheduleTone.set('success');
      this.scheduleMessage.set('Horario publicado. Los pacientes ya pueden agendar en esos horarios.');
    } catch (error) {
      this.scheduleTone.set('danger');
      this.scheduleMessage.set(errorMessage(error));
    } finally {
      this.savingSchedule.set(false);
    }
  }

  async openRecord(patient: Patient): Promise<void> {
    this.selectedPatientId.set(patient.patientId);
    this.loadingRecord.set(true);
    this.patientRecord.set(null);
    this.patientDocuments.set([]);
    this.patientsMessage.set('');
    try {
      const [record, documents] = await Promise.all([
        this.api.get<MedicalRecord>('/api/records', { patientId: patient.patientId }),
        this.api.get<MedicalDocument[]>('/api/records/documents', { patientId: patient.patientId }),
      ]);
      this.patientRecord.set(record);
      this.patientDocuments.set(documents);
    } catch (error) {
      this.patientsMessage.set(errorMessage(error));
    } finally {
      this.loadingRecord.set(false);
    }
  }
}
