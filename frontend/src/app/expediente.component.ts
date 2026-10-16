import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, Consent, Doctor, MedicalDocument, MedicalRecord, errorMessage, formatDateTime } from './api.service';
import { ExpedienteVistaComponent } from './expediente-vista.component';

/** Flujo 2: el paciente llena su expediente y decide quién lo ve. */
@Component({
  selector: 'midoc-expediente',
  standalone: true,
  imports: [FormsModule, ExpedienteVistaComponent],
  templateUrl: './expediente.component.html'
})
export class ExpedienteComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly record = signal<MedicalRecord | null>(null);
  readonly consents = signal<Consent[]>([]);
  readonly doctors = signal<Doctor[]>([]);
  readonly documents = signal<MedicalDocument[]>([]);
  readonly loading = signal(true);
  readonly uploading = signal(false);
  readonly saving = signal(false);
  readonly deletingDocumentId = signal<string | null>(null);
  readonly updatingConsentId = signal<string | null>(null);
  readonly message = signal('');
  readonly consentMessage = signal('');
  readonly formatDateTime = formatDateTime;
  readonly sexes = ['FEMENINO', 'MASCULINO', 'OTRO'];
  readonly bloodTypes = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'];

  form = { birthDate: '', sex: '', bloodType: '', allergies: '', chronicConditions: '', medications: '', notes: '' };
  doctorToGrant = '';

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    try {
      const [record, consents, doctors] = await Promise.all([
        this.api.get<MedicalRecord>('/api/records'),
        this.api.get<Consent[]>('/api/consents'),
        this.api.get<Doctor[]>('/api/doctors')
      ]);
      this.record.set(record);
      this.consents.set(consents);
      this.doctors.set(doctors);
      this.form = {
        birthDate: record.birthDate ?? '',
        sex: record.sex ?? '',
        bloodType: record.bloodType ?? '',
        allergies: record.allergies.join(', '),
        chronicConditions: record.chronicConditions.join(', '),
        medications: record.medications.join(', '),
        notes: record.notes ?? ''
      };
      await this.loadDocuments();
    } catch (error) {
      this.message.set(errorMessage(error));
    } finally {
      this.loading.set(false);
    }
  }

  async loadDocuments(): Promise<void> {
    try {
      this.documents.set(await this.api.get<MedicalDocument[]>('/api/records/documents'));
    } catch (error) {
      this.consentMessage.set(errorMessage(error));
    }
  }

  async uploadDocument(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.uploading.set(true);
    this.message.set('');
    try {
      await this.api.uploadDocument(file);
      this.message.set('Archivo agregado de forma privada a tu expediente.');
      await this.loadDocuments();
    } catch (error) {
      this.message.set(errorMessage(error));
    } finally {
      this.uploading.set(false);
      input.value = '';
    }
  }

  async deleteDocument(document: MedicalDocument): Promise<void> {
    if (!globalThis.confirm(`¿Eliminar ${document.name} del expediente?`)) return;
    this.deletingDocumentId.set(document.id);
    try {
      await this.api.delete(`/api/records/documents/${document.id}`);
      this.documents.update(items => items.filter(item => item.id !== document.id));
      this.message.set('Archivo eliminado del expediente.');
    } catch (error) {
      this.message.set(errorMessage(error));
    } finally {
      this.deletingDocumentId.set(null);
    }
  }

  formatSize(bytes: number): string {
    return bytes < 1_000_000 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1_000_000).toFixed(1)} MB`;
  }

  private list(value: string): string[] {
    return value.split(',').map(item => item.trim()).filter(Boolean);
  }

  async save(): Promise<void> {
    if (this.saving()) return;
    this.saving.set(true);
    try {
      this.record.set(await this.api.put<MedicalRecord>('/api/records', {
        birthDate: this.form.birthDate || null,
        sex: this.form.sex || null,
        bloodType: this.form.bloodType || null,
        allergies: this.list(this.form.allergies),
        chronicConditions: this.list(this.form.chronicConditions),
        medications: this.list(this.form.medications),
        notes: this.form.notes
      }));
      this.message.set('Expediente actualizado.');
    } catch (error) {
      this.message.set(errorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }

  async setConsent(doctorId: string, granted: boolean): Promise<void> {
    if (!doctorId || this.updatingConsentId()) return;
    this.updatingConsentId.set(doctorId);
    try {
      await this.api.post('/api/consents', { doctorId, granted });
      this.consentMessage.set(granted ? 'Acceso otorgado.' : 'Acceso revocado: el profesional ya no puede ver tu expediente.');
      this.doctorToGrant = '';
      this.consents.set(await this.api.get<Consent[]>('/api/consents'));
    } catch (error) {
      this.consentMessage.set(errorMessage(error));
    } finally {
      this.updatingConsentId.set(null);
    }
  }
}
