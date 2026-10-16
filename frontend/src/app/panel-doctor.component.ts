import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, DAYS, InventoryItem, MedicalDocument, MedicalRecord, Patient, Profile, Promotion, Subscription, errorMessage, formatDateTime, todayInMexico } from './api.service';
import { ExpedienteVistaComponent } from './expediente-vista.component';

interface BlockForm {
  day: number;
  start: string;
  end: string;
}

/** Flujo 3: suscripción de $20 USD/mes, horario y pacientes autorizados. */
@Component({
  selector: 'midoc-panel-doctor',
  standalone: true,
  imports: [FormsModule, ExpedienteVistaComponent],
  templateUrl: './panel-doctor.component.html'
})
export class PanelDoctorComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly subscription = signal<Subscription | null>(null);
  readonly loading = signal(true);
  readonly loadFailed = signal(false);
  readonly patients = signal<Patient[]>([]);
  readonly patientRecord = signal<MedicalRecord | null>(null);
  readonly patientDocuments = signal<MedicalDocument[]>([]);
  readonly inventory = signal<InventoryItem[]>([]);
  readonly promotions = signal<Promotion[]>([]);
  readonly inventoryMessage = signal('');
  readonly promotionMessage = signal('');
  readonly paying = signal(false);
  readonly savingSchedule = signal(false);
  readonly savingInventory = signal(false);
  readonly savingPromotion = signal(false);
  readonly subscriptionMessage = signal('');
  readonly scheduleMessage = signal('');
  readonly patientsMessage = signal('');
  readonly days = DAYS.map((name, value) => ({ name, value })).slice(1);
  readonly formatDateTime = formatDateTime;

  card = { cardHolder: '', cardNumber: '4242 4242 4242 4242', expMonth: 12, expYear: new Date().getFullYear() + 2, cvv: '123' };
  inventoryForm = { name: '', quantity: 0, unit: 'piezas' };
  promotionForm = { title: '', description: '', discountPercent: 10, start: todayInMexico(), end: todayInMexico(30) };
  blocks: BlockForm[] = [];

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.loadFailed.set(false);
    try {
      const me = await this.api.get<Profile>('/api/me');
      this.subscription.set(me.subscription ?? null);
      const doctor = me.doctor;
      if (doctor) {
        this.blocks = (doctor.schedule ?? []).map(b => ({ day: b.dia_semana, start: b.hora_inicio, end: b.hora_fin }));
        this.card.cardHolder = doctor.name;
      }
      await this.loadPatients();
      if (this.subscription()?.active) await this.loadBusinessLists();
    } catch (error) {
      this.loadFailed.set(true);
      this.subscriptionMessage.set(errorMessage(error));
    } finally {
      this.loading.set(false);
    }
  }

  async loadBusinessLists(): Promise<void> {
    try {
      const [inventory, promotions] = await Promise.all([
        this.api.get<InventoryItem[]>('/api/doctor/inventory'),
        this.api.get<Promotion[]>('/api/doctor/promotions')
      ]);
      this.inventory.set(inventory);
      this.promotions.set(promotions);
    } catch (error) {
      this.inventoryMessage.set(errorMessage(error));
    }
  }

  async saveInventoryItem(): Promise<void> {
    if (this.savingInventory()) return;
    this.savingInventory.set(true);
    try {
      await this.api.post('/api/doctor/inventory', this.inventoryForm);
      this.inventoryForm = { ...this.inventoryForm, name: '', quantity: 0 };
      this.inventoryMessage.set('Inventario actualizado.');
      await this.loadBusinessLists();
    } catch (error) {
      this.inventoryMessage.set(errorMessage(error));
    } finally {
      this.savingInventory.set(false);
    }
  }

  async deleteInventoryItem(item: InventoryItem): Promise<void> {
    try {
      await this.api.delete(`/api/doctor/inventory/${item.id}`);
      this.inventory.update(items => items.filter(value => value.id !== item.id));
      this.inventoryMessage.set('Insumo eliminado.');
    } catch (error) {
      this.inventoryMessage.set(errorMessage(error));
    }
  }

  async savePromotion(): Promise<void> {
    if (this.savingPromotion()) return;
    this.savingPromotion.set(true);
    try {
      await this.api.post('/api/doctor/promotions', this.promotionForm);
      this.promotionForm = { ...this.promotionForm, title: '', description: '' };
      this.promotionMessage.set('Promoción publicada en el marketplace durante las fechas indicadas.');
      await this.loadBusinessLists();
    } catch (error) {
      this.promotionMessage.set(errorMessage(error));
    } finally {
      this.savingPromotion.set(false);
    }
  }

  async deletePromotion(promotion: Promotion): Promise<void> {
    try {
      await this.api.delete(`/api/doctor/promotions/${promotion.id}`);
      this.promotions.update(items => items.filter(value => value.id !== promotion.id));
      this.promotionMessage.set('Promoción retirada del marketplace.');
    } catch (error) {
      this.promotionMessage.set(errorMessage(error));
    }
  }

  async loadPatients(): Promise<void> {
    if (!this.subscription()?.active) {
      this.patients.set([]);
      this.patientsMessage.set('Activa tu suscripción para ver a tus pacientes y sus expedientes.');
      return;
    }
    try {
      this.patients.set(await this.api.get<Patient[]>('/api/doctor/patients'));
      this.patientsMessage.set('');
    } catch (error) {
      this.patientsMessage.set(errorMessage(error));
    }
  }

  async pay(): Promise<void> {
    if (this.paying()) return;
    this.paying.set(true);
    try {
      const result = await this.api.post<Subscription>('/api/subscriptions/pay', this.card);
      this.subscriptionMessage.set(`Pago aprobado con ${result.cardBrand} terminación ${result.cardLast4}. Vigente hasta ${result.end}.`);
      await this.load();
    } catch (error) {
      this.subscriptionMessage.set(errorMessage(error));
    } finally {
      this.paying.set(false);
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
    this.savingSchedule.set(true);
    try {
      await this.api.put('/api/doctor/schedule', { blocks: this.blocks.map(b => ({ ...b, day: Number(b.day) })) });
      this.scheduleMessage.set('Horario publicado. Los pacientes ya pueden agendar en esos horarios.');
    } catch (error) {
      this.scheduleMessage.set(errorMessage(error));
    } finally {
      this.savingSchedule.set(false);
    }
  }

  async openRecord(patient: Patient): Promise<void> {
    this.patientRecord.set(null);
    this.patientDocuments.set([]);
    try {
      const [record, documents] = await Promise.all([
        this.api.get<MedicalRecord>('/api/records', { patientId: patient.patientId }),
        this.api.get<MedicalDocument[]>('/api/records/documents', { patientId: patient.patientId })
      ]);
      this.patientRecord.set(record);
      this.patientDocuments.set(documents);
    } catch (error) {
      this.patientsMessage.set(errorMessage(error));
    }
  }
}
