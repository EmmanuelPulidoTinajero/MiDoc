import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';

export type Role = 'PACIENTE' | 'DOCTOR' | 'CLINICA';

export interface SessionUser {
  id: string;
  email: string;
  role: Role;
  name?: string | null;
  doctorId?: string | null;
}

export interface Doctor {
  id: string;
  userId?: string;
  name: string;
  specialty: string;
  location: string;
  city?: string | null;
  description?: string | null;
  price: number;
  durationMin?: number;
  type?: Role;
  schedule?: ScheduleBlock[];
  promotions?: Promotion[];
}

export interface Promotion {
  id: string;
  title: string;
  description: string;
  discountPercent: number;
  start: string;
  end: string;
  active: boolean;
}

export interface InventoryItem {
  id: string;
  name: string;
  quantity: number;
  unit: string;
  updatedAt?: string;
}

export interface AppNotification {
  id: string;
  type: string;
  title: string;
  message: string;
  reference?: string | null;
  createdAt: string;
  read: boolean;
}

export interface ScheduleBlock {
  dia_semana: number;
  hora_inicio: string;
  hora_fin: string;
}

export interface Appointment {
  id: string;
  patientId: string;
  doctorId: string;
  dateTime: string;
  status: 'PENDIENTE' | 'CONFIRMADA' | 'CANCELADA' | 'COMPLETADA';
  reason?: string | null;
  patientName?: string | null;
  doctorName?: string | null;
  specialty?: string | null;
  location?: string | null;
  prescriptionId?: string | null;
}

export interface Consultation {
  prescriptionId: string | null;
  appointmentId: string;
  dateTime: string;
  doctorName: string;
  specialty: string;
  diagnosis: string;
  treatment: string;
  notes?: string | null;
}

export interface MedicalRecord {
  patient_id: string;
  allergies: string[];
  notes: string;
  birthDate?: string | null;
  sex?: string | null;
  bloodType?: string | null;
  chronicConditions: string[];
  medications: string[];
  updatedAt?: string | null;
  patient: { id: string; name?: string | null; email?: string | null };
  consultations: Consultation[];
}

export interface MedicalDocument {
  id: string;
  name: string;
  contentType: string;
  size: number;
  lastModified: string;
  downloadUrl: string;
}

export interface Consent {
  doctorId: string;
  doctorName: string;
  specialty: string;
  granted: boolean;
  updatedAt: string;
}

export interface Subscription {
  status: string;
  amount: number;
  start?: string | null;
  end?: string | null;
  cardBrand?: string | null;
  cardLast4?: string | null;
  active: boolean;
}

export interface Patient {
  patientId: string;
  name: string;
  email: string;
  accessSince: string;
}

export interface Profile extends SessionUser {
  phone?: string | null;
  doctor?: Doctor;
  subscription?: Subscription;
}

interface Session {
  token: string;
  user: SessionUser;
}

const STORAGE_KEY = 'midoc.session';

/** URL de la API: en localhost el backend local; en S3 la que publica Terraform en config.json. */
export let API_URL = '';
export let API_CONFIG_ERROR = '';

export async function loadConfig(): Promise<void> {
  API_CONFIG_ERROR = '';
  if (['localhost', '127.0.0.1', '[::1]'].includes(globalThis.location.hostname)) {
    API_URL = 'http://localhost:3000';
    return;
  }
  try {
    const response = await fetch('config.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('No fue posible cargar la configuración de la API.');
    const config = (await response.json()) as { apiUrl?: string };
    if (!config.apiUrl || !config.apiUrl.startsWith('https://')) {
      throw new Error('La dirección de la API no es válida o no usa HTTPS.');
    }
    API_URL = config.apiUrl.replace(/\/$/, '');
  } catch (error) {
    API_CONFIG_ERROR = error instanceof Error ? error.message : 'No fue posible iniciar MiDoc.';
  }
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly session = signal<Session | null>(this.readSession());

  readonly user = computed(() => this.session()?.user ?? null);
  readonly isPatient = computed(() => this.user()?.role === 'PACIENTE');
  readonly isDoctor = computed(() => ['DOCTOR', 'CLINICA'].includes(this.user()?.role ?? ''));

  get<T>(path: string, params: Record<string, string> = {}): Promise<T> {
    return this.call(this.http.get<{ data: T }>(this.url(path), { headers: this.headers(), params: new HttpParams({ fromObject: params }) }));
  }

  post<T>(path: string, body: unknown = {}): Promise<T> {
    return this.call(this.http.post<{ data: T }>(this.url(path), body, { headers: this.headers() }));
  }

  put<T>(path: string, body: unknown): Promise<T> {
    return this.call(this.http.put<{ data: T }>(this.url(path), body, { headers: this.headers() }));
  }

  patch<T>(path: string, body: unknown): Promise<T> {
    return this.call(this.http.patch<{ data: T }>(this.url(path), body, { headers: this.headers() }));
  }

  delete<T>(path: string): Promise<T> {
    return this.call(this.http.delete<{ data: T }>(this.url(path), { headers: this.headers() }));
  }

  async uploadDocument(file: File): Promise<void> {
    const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
    const types: Record<string, string> = { pdf: 'application/pdf', jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', dcm: 'application/dicom', dicom: 'application/dicom' };
    const contentType = !file.type || file.type === 'application/octet-stream' ? types[extension] ?? file.type : file.type;
    const request = await this.post<{ url: string; fields: Record<string, string> }>(
      '/api/records/documents', { name: file.name, contentType, size: file.size }
    );
    const form = new FormData();
    for (const [key, value] of Object.entries(request.fields)) form.append(key, value);
    form.append('file', file);
    const response = await fetch(request.url, { method: 'POST', body: form });
    if (!response.ok) throw new Error('No se pudo guardar el archivo. Intenta nuevamente.');
  }

  async login(email: string, password: string): Promise<void> {
    const result = await this.raw(this.http.post<Session>(this.url('/api/auth/login'), { email, password }));
    this.saveSession(result);
    await this.refreshProfile();
  }

  async register(body: Record<string, unknown>): Promise<void> {
    this.saveSession(await this.raw(this.http.post<Session>(this.url('/api/auth/register'), body)));
  }

  async refreshProfile(): Promise<Profile> {
    const profile = await this.get<Profile>('/api/me');
    const current = this.session();
    if (current) {
      this.saveSession({ token: current.token, user: { ...current.user, name: profile.name, doctorId: profile.doctorId } });
    }
    return profile;
  }

  logout(): void {
    localStorage.removeItem(STORAGE_KEY);
    this.session.set(null);
  }

  private url(path: string): string {
    if (!API_URL) throw new Error(API_CONFIG_ERROR || 'La API no está configurada.');
    return `${API_URL}${path}`;
  }

  private headers(): Record<string, string> {
    const token = this.session()?.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  private async call<T>(request: Observable<{ data: T }>): Promise<T> {
    return (await this.raw(request)).data;
  }

  private async raw<T>(request: Observable<T>): Promise<T> {
    try {
      return await firstValueFrom(request);
    } catch (error) {
      if (error instanceof HttpErrorResponse) {
        if (error.status === 401 && this.session()) {
          this.logout();
        }
        const message = (error.error as { error?: string } | null)?.error;
        throw new Error(message ?? (error.status === 0 ? 'No fue posible conectar con la API' : `Error ${error.status}`));
      }
      throw error;
    }
  }

  private readSession(): Session | null {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as Session | null;
    } catch {
      return null;
    }
  }

  private saveSession(session: Session): void {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    this.session.set(session);
  }
}

/** Mensaje legible de cualquier error. */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Ocurrió un error inesperado';
}

export const DAYS = ['', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Mexico_City' });
}

export function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Mexico_City' });
}

export function todayInMexico(offsetDays = 0): string {
  const date = new Date(Date.now() + offsetDays * 86_400_000);
  return date.toLocaleDateString('en-CA', { timeZone: 'America/Mexico_City' });
}
